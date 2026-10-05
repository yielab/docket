# Pod Blueprints Specification

**Version**: 1.21.0
**Status**: Implemented
**Last Updated**: 2026-10-03

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
  `gateContract`, `toolProfile`, `deniedTools`) — see `role-archetypes.spec.md`. A blueprint's
  `roles` list is a roster of archetype names; this spec does not redefine what an archetype is
- The pipeline format itself (steps, gates, rework edges, variables) — see
  `pipeline-format.spec.md`. A blueprint's `defaultPipeline` is one `PipelineSpec` value; this spec
  only covers which pipeline each built-in blueprint attaches and why
- Executing a pipeline — the executor (ROADMAP Phase 16 W-2/W-8, shipped) is specified in
  `pod-dispatch.spec.md`. A pod dispatched with no caller-supplied spec runs its blueprint's
  `defaultPipeline`: `core.dispatch.effective_pipeline` resolves the Lead's `blueprint` meta
  through `core.blueprints.get_blueprint`, falling back to `core.pipeline.default_pipeline()`
  when the meta is absent, empty, or names an unknown blueprint — see `pod-dispatch.spec.md`,
  "Pipeline order and participation", for the exact resolution order. A `research`, `content`, or
  `ops` pod dispatched that way now runs its full roster and gates, not only its Lead step.
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
   applies to `scope`/`modelClass`/`gateContract.kind`.
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
   Implementer's convention) and its Monitor step on human approval. Each of the three **MUST**
   declare `instructions` (`pipeline-format.spec.md`'s "Steps" Requirement 8) on its `lead` step
   naming that pipeline's own next role (P27-5) — `research`: the Researcher; `content`: the
   Writer; `ops`: the Operator — instead of the built-in `lead` archetype's generic Implementer
   text, which none of these three pods has a member for. `software` and `agentic-product` declare
   no `instructions` on their `lead` step and **MUST** stay byte-identical to
   `core.pipeline.default_pipeline()`.
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
   `config.pod_scratch_dir()` auto-provisions a pod's scratch directory. `docket init` always
   supplies a location (the current directory when none is passed), so this path is reached from
   a `--from` entry without `workDir` or a `POST /pods` body without `path`.
3. Every workspace-contract file a `workdir`-kind member's provisioning writes (`WORKFLOW_AUTO.md`,
   `MEMORY.md`, today's daily log) **MUST** anchor the working directory, not imply a git-tracked
   codebase — no "cd into the codebase" language, no `## Your codebase` heading. A `codebase`-kind
   member's contract files **MUST** be byte-for-byte unaffected by this distinction (verified by
   `tests/integration/test_provisioning_contract.py`'s `TestSeedContractWorkdir`).
4. A pod member added later to an existing pod (`docket pod <project> add <role>`) **MUST**
   inherit the pod's `workspaceKind`/working-directory (or codebase) from an existing member,
   never defaulting to `codebase`-kind for a pod that was provisioned `workdir`-kind.
5. `docket doctor` **MUST NOT** flag a `workdir`-kind pod member as broken for lacking a `TOOLS.md`
   — `TOOLS.md` is written only for an Implementer with allocated resources or a `verifyCmd`
   (`workspace-structure.spec.md`), which no built-in `workdir` blueprint's roster includes.

### CLI surface

1. `docket init <project> [location] [--blueprint <name>]` **MUST** resolve the blueprint (default
   `software`) before provisioning anything, and **MUST** fail cleanly (exit 1, nothing
   provisioned) if `<name>` is not a registered blueprint. `docket init` is non-interactive: the
   location defaults to the current directory and the project id to that directory's name.
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
   `docket blueprints add` — the five built-ins in `core/blueprints.py` are Python literals and
   are the entire registry. A future card may add a `~/.docket/docket-blueprints.json` user
   overlay following the same pattern `docket-roles.json` established; until then, composing a
   custom pod shape means adding roles to an existing pod with `docket pod <project> add <role>`
   after provisioning from the closest built-in blueprint.

### Pod manifests: apply

A blueprint shapes a pod at `docket init` time; this section covers the complementary case — a
team shape applied to a pod that already exists (ADR 0009). Before this section, applying a
shipped recipe to an existing pod meant a per-recipe sequence of `docket roles add`/`docket pod
<p> add <role>`/`docket pod <p> config set pipeline <file>` commands; `docket pod <p> apply
<dir>` composes the same writers into one command, once a directory shape becomes common enough
(a pod reproduced on a second machine) to be worth automating.

1. `docket pod <project> apply [<name|dir>] [--dry-run] [--json]` **MUST** read *dir* (default
   `<codebase>/.docket/`, from the pod Lead's own `codebase` meta; an argument that is not an
   existing directory resolves as a shipped recipe name through the same `resolve_recipe`
   requirement 8 gives `docket init --recipe`, and an unresolvable name exits 1 naming the
   shipped recipes) as: an optional `roles/*.yaml`
   directory (role definitions, the same wire format `role-archetypes.spec.md` defines), an
   optional `policies/*.json` directory (guardrail policies, the same schema
   `core.policy.validate_policy` enforces), an optional `pipeline.yaml` (or the file named by
   `pod.yaml`'s `pipeline` key), and an optional `pod.yaml` manifest carrying exactly five
   top-level keys — `members` (a list of role names to add if absent), `settings` (a mapping of
   any `docket pod <p> config set <key> <value>` key), `pipeline` (a filename inside *dir*,
   default `pipeline.yaml` when that file exists), `description` (a string; read only for
   display — requirement 9 — and never applied to the pod), and `exporters` (a list of
   observability-destination names — requirement 11 — reported, never activated). An
   unrecognized top-level `pod.yaml` key, a `members`/`settings` value of the wrong type, a
   `description` that is not a string, or an `exporters` entry that is not a plain string naming
   a catalog exporter, **MUST** be rejected before anything else is read. *dir* **MAY** also carry
   an optional
   `skills/<name>/SKILL.md` directory per skill (P31-6, ADR 0013 §3 rule 8): each `<name>/` is a
   complete Agent Skill, applied whole into this pod's own `config/skills/<name>/` (see
   requirement 6's digest and "Pod manifests: export" below).
2. A role in `roles/*.yaml` **MUST** be written into *that pod's own* role overlay
   (`core.config.pod_config_dir(project)/roles.json`), the same target `docket roles add
   --pod <project> <file.yaml>` already writes to — never the global user overlay
   (`~/.docket/docket-roles.json`). `core/pod.py`'s roster helpers (the id-parsing
   `_role_names`/`parse_member_id` that `pod_full_roster`/`members_of` depend on to resolve a
   pipeline's roster) resolve that pod's own overlay too (`core.archetypes.load_registry
   (project)`), so a role written into the pod-scoped overlay is both provisionable as a member
   and resolvable back out of the roster a pipeline dispatches against — and stays invisible to
   every other pod, matching this command's `<project>`-scoped surface.
3. A file in `policies/*.json` **MUST** be validated with `core.policy.validate_policy` and, once
   valid, written byte-for-byte into *that pod's own* policy directory
   (`core.config.pod_config_dir(project)/policies/<name>`) — the same directory
   `core.policy.policy_files(project)` reads at evaluation time and `export_pod` already copies
   from — never the fleet-wide `$POLICIES_DIR`. A policy file whose bytes already match the pod's
   copy plans as `skip`; a different one already present plans as `replace`; an invalid policy
   file (a non-empty `validate_policy` result) **MUST** be rejected before anything else is
   written, naming the offending file.
4. `apply` **MUST** validate everything before writing anything: each `roles/*.yaml` definition
   (`role-archetypes.spec.md`'s schema), every `policies/*.json` file
   (`core.policy.validate_policy`), every `members` entry against the role registry *as it would
   be after* the recipe's own `roles/*.yaml` are added, the resolved `pipeline.yaml` against the
   roster *as it would be after* `members` join (no skipped step,
   `core.orchestrator.resolve_plan`), and every `settings` entry through the same
   `core.pod.PodSettings` validators `config set` uses. A validation failure **MUST** exit 1
   naming the offending item and **MUST NOT** write any role, policy, member, pipeline binding, or
   setting — including one that validated cleanly earlier in the same run.
5. `apply` **MUST** be additive and idempotent: an item whose target state already matches disk
   plans and reports as `skip`; a member is only ever added, never replaced or removed; a role,
   policy, pipeline binding, or setting already present with different content plans as `replace`.
   Applying the same directory twice in a row **MUST** plan every item `skip` the second time and
   write nothing. `--dry-run` **MUST** print the plan and write nothing.
6. A successful `apply` that wrote at least one item **MUST** write exactly one `pod.apply` audit
   entry naming every planned item and its action; an all-`skip` plan **MUST NOT** write a new
   audit entry. Every successful `apply` — an all-`skip` plan included — **MUST** also record this
   pod's configuration of record (ADR 0012 §2 rule 5, amended by ADR 0013 §1 rule 3) in its
   settings: `configSource` (the absolute *dir*) and `configDigest`
   (`core.pod_apply.directory_digest(dir)` — a sha256 hex digest over the sorted relative paths
   and bytes of every file `discover_config_paths` returns plus any `plugins/*.py` and any file
   under `skills/**`, excluding the generated `.schemas/`), so composing a second recipe onto an
   already-configured pod — even one
   whose every item plans `skip` — still moves the record to name the directory just applied.
   Both **MUST NEVER** be written by `docket pod <p> config set`, which **MUST** refuse both keys
   naming `apply` as their writer; a `pod.yaml` `settings` mapping carrying either key is refused
   the same way any key outside the settable set already is (requirement 1). `docket config
   explain <agent>` reports `configSource`, `configDigest`, and `drift` — `"yes"` when recomputing
   `directory_digest` against the still-present `configSource` disagrees with the recorded
   `configDigest`, `"no"` when it agrees, `""` when there is no recorded source or its directory
   is gone (drift is then unknown, never asserted either way).
7. Removing a role, policy, member, pipeline binding, or setting stays out of this command's
   scope — `docket pod <p> remove <member-id>`, `config unset <key>`, and manual file deletion
   remain the explicit way to undo what a recipe added.
8. `docket init` **MUST** discover a present `<location>/.docket/` (the same directory shape and
   default this section reads) and, before provisioning anything, validate every document under
   it (`core.config_docs.validate_directory`); any error **MUST** exit 1 naming the offending file
   and field, with no pod provisioned. After provisioning succeeds, `init` **MUST** plan and apply
   that directory through this section's own `plan_apply`/`apply` (never a second write path), and
   the resulting `pod.apply` audit entry is this requirement's, not a duplicate. `docket init
   --recipe <name|dir>` **MUST** resolve *name|dir* through `core.pod_apply.resolve_recipe`: a
   directory path if one exists at that location, else the operator's own
   `config.user_recipes_dir()/<name|dir>`, else a shipped recipe under `config.recipes_dir()` —
   three scopes, nearest wins by name (ADR 0013 §1 rule 4) — and apply it the same way; an
   unresolvable name **MUST** exit 1 naming both scopes' recipe names, before provisioning.
   `--recipe` together with a present `.docket/` **MUST** exit 1 naming both sources, before
   provisioning — two sources of record is an ambiguity this command refuses rather than picks
   between. `--no-apply` **MUST** provision the pod and skip applying either source, instead
   printing the `docket pod <p> apply <dir>` command that would apply it.
9. **Recipe summary (ADR 0013 §1 rule 1).** A directory's scope is derived from its contents,
   never a declared field: `core.pod_apply.summarize_recipe(directory)` reads, without needing a
   project or a role registry, the count of `roles/*.yaml|yml|json`, `policies/*.yaml|yml|json`,
   `plugins/*.py`, and `skills/*/SKILL.md` directories directly under *directory*; `pod.yaml`'s
   own `members`/`settings` entry counts (`0` when absent or of the wrong type); the bound
   pipeline document's own `name` (the file `pod.yaml`'s `pipeline` key names, or `pipeline.yaml`
   when present and no key names one — the same resolution requirement 1 uses — loaded through
   `core.pipeline.load_pipeline`; `""` when no pipeline file resolves or it fails to parse); and
   `pod.yaml`'s own `description` (`""` when absent); and `pod.yaml`'s own `exporters` list,
   filtered to string entries only (unvalidated against the catalog — that check is
   requirement 11's, `plan_apply`'s job, not this read-only summary's). `RecipeSummary.render()`
   **MUST** render every count, always in the same order — `roles`, `policies`, `members`,
   `pipeline`, `plugins`, `skills`, `settings` — as one line, e.g. `roles 1 · policies 1 ·
   members 1 · pipeline secure-build · plugins 0 · skills 0 · settings 0` (`pipeline none` when
   no pipeline resolves), with `· exporters <name>[, <name>...]` appended only when the recipe
   names at least one (e.g. `... · settings 0 · exporters langfuse`). `docket validate <dir>` (see
   `config-format.spec.md`) prints this summary after its per-file lines; `docket pod <p> apply`
   and `docket init --recipe`/a discovered `.docket/` print it, and the directory's own
   `description` when set, before the plan itself (`cli-interface.spec.md`).
10. **Recipe listing (ADR 0013 §1 rule 5).** `core.pod_apply.list_recipes()` **MUST** return one
    `RecipeInfo` (`name`, `scope` — `"operator"` or `"shipped"` — `directory`, `summary`) per
    name reachable across both scopes `resolve_recipe` reads, sorted by name; a name present in
    both **MUST** resolve to the operator's own directory, matching requirement 8's resolution
    order. `docket recipes list [--json]` **MUST** print every entry — name, scope, a derived
    `brings` (the non-zero summary parts joined with `+` in summary order, e.g. `roles+members+pipeline+policies`; `nothing` for an empty directory) -- never a stored field, matching requirement 9's rule that scope is always derived. `docket recipes
    show <name|dir> [--json]` **MUST** resolve *name|dir* through the same `resolve_recipe`
    (an unresolvable name **MUST** exit 1 naming both scopes' recipe names, matching
    requirement 8) and print that directory's scope (omitted for a bare path outside both
    scopes), directory, derived summary, and its `README.md` body when the file is present.
    Neither subcommand **MUST** install, remove, fetch, or write anything — `docket pod <p>
    apply`/`docket init --recipe` remain the only writers.
11. **Recipe exporters (ADR 0014 rule 7): a recipe may name a destination, never carry one.**
    `pod.yaml`'s optional `exporters` list names zero or more observability destinations by their
    `core.exporter.load_catalog()` name. `plan_apply` **MUST** validate every entry before
    anything else is written: an entry that is not a plain string matching the exporter name
    shape (`^[a-z0-9][a-z0-9-]*$`) — a document, a URL, or a credential-shaped string included —
    **MUST** be rejected naming `exporters` and the offending entry, and an entry that does not
    resolve in the live catalog **MUST** be rejected the same way naming the unknown name. A
    validated list **MUST** be recorded under `core.pod.PodSettings`'s `exporters` key — a
    recorded key exactly like `configSource`/`configDigest` (requirement 6): written only by
    `apply`, on every successful `plan_apply`-validated run (an all-`skip` plan included, and
    overwriting rather than merging with what a prior apply recorded), and refused by `docket pod
    <p> config set exporters` naming `apply` as its writer. `apply` **MUST NOT** write to
    `docket-exporters.json` or otherwise change any exporter's `enabled` state — activation stays
    global, one operator's command (D-22), never a side effect of applying a team's configuration.
    `apply` (and therefore `init --recipe`/a discovered `.docket/`) **MUST** print, after the
    plan, one line per named exporter — its state from `core.exporter.activation_state` (called
    with `health=None`: this read-only listing does not consult `exporters-health.json`) and,
    unless already `enabled`, the exact `docket exporters enable <name>` command — e.g. `exporter
    langfuse: disabled -> docket exporters enable langfuse` or `exporter otel-collector: enabled`.
    `export_pod` **MUST** write this pod's recorded `exporters` list back into `pod.yaml` (see
    "Pod manifests: export" below) when at least one is set — unlike `configSource`/
    `configDigest`, which describe provenance and are never written back, `exporters` is part of
    what a recipe declares and round-trips like `members`. `docket recipes show <name|dir>`
    **MUST** print the same per-name state lines, from the directory's own declared list
    (requirement 9), without requiring a project.

### Pod manifests: export

The write direction the deferred manifest carried since "apply" shipped: `apply` composes a
directory *onto* a pod; `export` writes one back out, in the same shape, so a pod already
configured by hand — or evolved past whatever recipe seeded it — can be reproduced on a second
machine, the trigger `docket pod <p> apply` itself named as deferred.

1. `docket pod <project> export [<dir>]` **MUST** write exactly this pod's own scope — *dir*
   defaults to `<codebase>/.docket/` (the pod Lead's own `codebase` meta, the same default
   "Pod manifests: apply" requirement 1 reads) when omitted — in the same directory shape
   `apply` reads, every YAML file in the **short form** (config-format.spec.md,
   "Short-form export") with a leading `# yaml-language-server:` header: `roles/<name>.yaml`
   (this pod's own role overlay entries only —
   `core.archetypes.load_registry(project).source_of(name) == "pod:<project>"` — each rendered
   through `core.archetypes.to_short_role()`, the inverse of `normalize_role`) plus a paired
   `roles/<name>.md` holding that role's instructions (`soulTemplate`, and — when it is not the
   generated starter template — a `## AGENTS` section with `agentsTemplate`); `policies/
   <stem>.yaml` (every file already present in this pod's own policy directory,
   `core.config.pod_config_dir(project)/policies/`, rendered through
   `core.policy.to_short_policy()`, the inverse of `normalize_policy`, never a byte copy); a
   `pipeline.yaml` holding the pod's bound pipeline copy verbatim
   (`core.pod.bound_pipeline_path(project)`, carrying no schema header of its own since it is
   not regenerated) when `PodSettings.pipeline` is set; and a `pod.yaml` manifest with `kind:
   pod` and `name: <project>` written first, then `members` (every non-Lead role this pod's
   roster has, `core.dispatch.pod_full_roster(project)`), `settings` (every key in
   `PodSettings.KEYS` whose stored value differs from that model's own default — a key at its
   default is never written, so a fresh pod exports an empty `settings` mapping; `configSource`/
   `configDigest`, outside `KEYS`, are never written here regardless of value — requirement 6
   above), and `exporters` (this pod's recorded `exporters` list, requirement 11, written only
   when non-empty — unlike `configSource`/`configDigest`, this key round-trips like `members`).
   `export` **MUST NOT** write a
   `pipeline` key inside `pod.yaml`: the default `pipeline.yaml` filename `apply` already
   resolves makes one redundant, matching every shipped recipe's own `pod.yaml`. A recipe's own
   `description` (requirement 9 above) is read-only display prose that `apply` never stores on
   the pod, so `export` has nothing to write it back from and **MUST NOT** write a `description`
   key — a round trip through `apply`/`export` drops a recipe's description, unlike every other
   manifest key. `export` **MUST** also copy *project*'s own `config/skills/` directory
   byte-for-byte into `skills/<name>/SKILL.md` (P31-6) per skill — unlike a role or policy, a
   skill is not regenerated, since it carries its own files rather than a wire document this
   module knows how to re-render. `export`
   **MUST** also copy the four published config-v1 JSON Schemas into `<dir>/.schemas/`
   (config-format.spec.md, "Published schemas") so every header resolves without reaching
   outside the export; `apply`/`discover_config_paths` never look under `.schemas/`.
2. Global scope is never exported — it is the operator's, not the team's. The global role overlay
   (`~/.docket/docket-roles.json`), fleet-wide policies (`~/.docket/policies/`), other pods, and
   this pod's own secrets, sessions, traces, and task queue are all out of scope; only what
   `pod_config_dir(project)` and the bound-pipeline copy hold is written.
3. `docket pod <project> export [<dir>]` **MUST** refuse a non-empty *dir* — including the
   defaulted `<codebase>/.docket/` — unless `--force` is given, so a stray argument (or an
   accidental bare `export`) cannot silently overwrite an operator's existing directory; an empty
   or not-yet-existing *dir* always succeeds. `--force` **MUST** proceed and write over any
   same-named file already there. A successful export **MUST** write one `pod.export` audit entry
   naming *project* and *dir*, matching every other pod-scope writer in this module.
4. Round trip is this pair's own proof, not a separate contract: exporting a pod, applying the
   result to a second pod in a fresh `DOCKET_HOME`, and comparing `docket config explain --json`
   for the matching members **MUST** agree once ids and paths specific to each pod are normalized
   away — the same guarantee `apply`'s validation (requirement 3 above) already gives a directory
   `export` produced. Because a role or policy is regenerated (never byte-copied), `plan_apply`
   **MUST** compare a role by its normalized `RoleArchetype.to_wire()` and a policy by its
   parsed (`core.policy.read_policy`) content, not by raw text, so re-planning a pod's own
   export against itself plans every item `skip`.

### The recipe library

A recipe's scope is derived from what its directory holds, never declared (ADR 0013): a
`pod.yaml` naming only `members` plans roles/members/pipeline, one holding only `policies/`
plans policy items only, and `plan_apply` treats every part as optional either way (see "Pod
manifests: apply" requirement 1). The shipped library groups by what a directory contains, not
by a declared field:

| Kind | Recipe | What `apply` plans on a lean pod |
| --- | --- | --- |
| Team | `secure-build` | roles + members + pipeline + policies |
| Team | `research-review` | roles + members + pipeline |
| Team | `ops-approval` | members + pipeline + policies |
| Policy pack | `git-safety` | policies only |
| Policy pack | `no-egress` | policies only |
| Policy pack | `secrets-guard` | policies only |
| Policy pack | `prod-approval` | policies only |
| Methodology | `tdd` | members (`tester`); a pipeline: `red` (Implementer writes one failing test) -> `check-red` (a `run` command step routed `on: {pass: fail, fail: green}`, so an unexpectedly passing test fails the task outright) -> `green` (Implementer, its own verify command) -> `test` (Tester, PASS/FAIL) |
| Methodology | `spec-first` | members (`writer`, `critic`, `reviewer`); a pipeline: `spec` (Writer) -> `approve-spec` (Critic, APPROVE/REJECT, bounded rework to `spec`) -> `build` (Implementer, its own verify command) -> `review` (Reviewer, APPROVE/REQUEST-CHANGES, bounded rework to `build`) |
| Methodology | `reflexion` | members (`critic`, `tester`); a pipeline: `build` (Implementer, its own verify command) -> `critique` (Critic, APPROVE/REQUEST-CHANGES, bounded rework to `build`, two cycles) -> `test` (Tester, PASS/FAIL) |
| Methodology | `dual-review` | members (`reviewer`, `critic`); a pipeline: `build` (Implementer, its own verify command) -> a `parallel` group of a Reviewer and a Critic, each falling back to its own role's default verdict gate |
| Methodology | `frugal` | members (`reviewer`); `settings` (`budgetUsd`, `maxReworkCycles`, `turnTimeoutS`); a pipeline: `plan` (Lead, `model: cheap`) -> `build` (Implementer, its own verify command) -> `review` (Reviewer, `model: cheap`, APPROVE/REQUEST-CHANGES, bounded rework to `build`) |
| Methodology | `spec-writer` | no added members; a pipeline: `write-tests` (Implementer, `model: cheap`, custom instructions for test writing) -> `build` (Implementer, its own verify command) |
| Methodology | `cross-family-review` | members (`reviewer`); a pipeline: `build` (Implementer, its own verify command) -> `review` (Reviewer, `model: openai/gpt-4.1-mini`, APPROVE/REQUEST-CHANGES, bounded rework to `build`) |
| Methodology | `anti-tautology` | no added members; a pipeline: `plan` (Lead) -> `build` (Implementer, its own verify command) -> `check-tests-fail-on-base` (a `run` command step that runs the test files added or changed since `DOCKET_BASE_COMMIT` in a disposable worktree of that commit and fails the task if they pass there; overridable by `ANTI_TAUTOLOGY_GLOB`/`ANTI_TAUTOLOGY_RUNNER`) |
| Methodology | `mutation` | no added members; a pipeline: `plan` (Lead) -> `build` (Implementer, its own verify command) -> `check-mutation-score` (a `run` command step that runs `mutmut`, which must be installed, over the source files changed since `DOCKET_BASE_COMMIT` and fails the task below `MUTATION_THRESHOLD`, default 80; scoped by file, not by line) |

A policy pack's `pod.yaml` carries `kind: pod`, `name`, and `description` only — no `members`,
`settings`, or `pipeline` key — so applying one to any pod changes no roster and no dispatch
step; its guardrails narrow what a role already in that pod's own pipeline may do. Every policy
pack states its rules with the structured predicates `core/policy.py::_predicate_matches`
already evaluates (`tool`, `path`, `branch`, `anyOf`), not free text, so a pack's guardrail
fires on the call itself: `git-safety` blocks force-push, hard reset, forced clean, forced
branch delete, forced checkout, and a global git config edit, and asks before a push that names
or is made from a protected branch (`main`/`master`/`production`/`prod`); `no-egress` asks
before a bash-run network client, a package install, or a `fetch` call; `secrets-guard` blocks a
write/edit whose path looks like a credential file (`.env`, `.pem`, `.key`, `id_rsa`, `.p12`) or
whose rendered text carries a private-key header, an AWS access-key id shape, or a bearer-token
shape, and redacts the same shapes from output; `prod-approval` asks before an implementer or
operator runs a deploy/production-shaped command, generalising `ops-approval`'s own policy
beyond the operator role. `secure-build`'s and `ops-approval`'s own policies are stated the same
way (an `anyOf` of `{tool, path}` pairs plus a `matches` for text; a `tool: bash` predicate
beside the existing `matches`, respectively) rather than the free-text match either used before.
Each methodology recipe is expressed only with the dialect that already exists (`verify`,
`verdict`, `on:` with `max`, `parallel`, `run:`, `model:`, `settings`) — no new pipeline-format or
pod-manifest field was added to ship these five. Every recipe's own `README.md` names the
practice, its one-line source idea, what docket's gates make structural about it (as opposed to
merely advisory), and how to undo it. `tdd`'s `check-red` step runs the literal shell command
`python3 -m pytest -q`: `pipeline-format.spec.md`'s `run` field carries no `${var}`-style
interpolation (only a step's own `instructions` does), so it cannot reference a pod's own verify
command, and the recipe's README says to edit the line by hand for a project whose test runner
differs.

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

### Provisioning a research pod

```bash
$ docket init my-market-scan /home/user/work/my-market-scan --blueprint research
→ Provisioning 'research' pod 'my-market-scan' (lead, researcher, analyst, writer, critic)...
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
✗ Error: unknown blueprint 'wizard-pod'; valid blueprints: software, research, content, ops, agentic-product
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
  `tests/unit/core/test_blueprints.py`'s `TestPipelineGateFidelity`).

## Changelog

### Unreleased

- **P37-5: `anti-tautology` and `mutation` recipes join the library (Phase 37, ADR 0019 §3).** Two methodology recipes ship as `templates/recipes/<name>/` directories, data only: `anti-tautology` fails a task whose new or changed test files pass on `DOCKET_BASE_COMMIT`, and `mutation` fails it when `mutmut` kills less than a threshold of the mutants in the files changed since that commit. Each is one `run` command step (`python3 -c`, classified `allow`) after `plan` (Lead) and `build` (Implementer, verify); no core code changed.
- **P37-6: `spec-writer` and `cross-family-review` recipes join the library (Phase 37, ADR 0019 §6).** Two methodology recipes ship as `templates/recipes/<name>/` directories: `spec-writer` (no new members; `write-tests` Implementer step with `model: cheap` custom instructions, then `build` Implementer step) and `cross-family-review` (members `reviewer`; `build` Implementer step, then `review` Reviewer step with `model: openai/gpt-4.1-mini` from a different provider family). Each carries a `pod.yaml` and `pipeline.yaml` expressed only with the existing pipeline dialect.

### Version 1.21.0 (2026-10-03)

- Stopped naming `editRights` as an archetype field (no users; legacy compatibility removed —
  `editRights` no longer gets any special handling anywhere). The "does NOT cover" archetype field
  list now names `deniedTools` instead, and Blueprint schema requirement 2's list of closed sets
  is `scope`/`modelClass`/`gateContract.kind`, matching role-archetypes.spec.md 1.22.0.

### Version 1.20.0 (2026-09-27)

- **P32-8: a recipe names its destinations (ADR 0014 rule 7).** New requirement 11: `pod.yaml`
  gains an optional `exporters: [<name>, ...]` list, validated against
  `core.exporter.load_catalog()` by `plan_apply` (a non-string, malformed-shaped, or unknown
  name is refused naming `exporters`, before anything else is written); recorded under
  `core.pod.PodSettings`'s new `exporters` key exactly like `configSource`/`configDigest`
  (requirement 6) — written only by `apply`, refused by `config set`. `apply`/`init --recipe`
  print one line per name from `core.exporter.activation_state` (`health=None`) after the plan,
  and `docket recipes show` prints the same lines from the directory's own declared list;
  neither activates anything or writes `docket-exporters.json`. `summarize_recipe` (requirement
  9) reads the declared list and `RecipeSummary.render()` appends `· exporters <name>, ...` when
  non-empty. `export_pod` (requirement 1, "Pod manifests: export") writes the recorded list back
  into `pod.yaml` when set, unlike the provenance-only `configSource`/`configDigest`. See
  `config-format.spec.md` 1.5.0 and `cli-interface.spec.md` for the manifest-key and CLI sides.

### Version 1.19.0 (2026-09-27)

- **`brings`, not `kind`; `pipeline none`.** Requirement 10's listing derives `brings` (the
  non-zero summary parts joined with `+`) instead of a one-word `kind` that could not tell a
  methodology recipe from a team; requirement 9's `render()` prints `pipeline none` when no
  pipeline resolves, so a policy pack's summary line reads as a sentence. Two skills join the
  library: `tdd` ships `test-first`, `spec-first` ships `writing-a-spec`.

### Version 1.18.0 (2026-09-27)

- **P31-6: skills join the shapes `apply`/`export` carry (ADR 0013 §3 rule 8).** "Pod manifests:
  apply" requirement 1 gains an optional `skills/<name>/SKILL.md` directory per skill, applied
  whole into the pod's own `config/skills/<name>/` (`core.pod_apply._plan_skills`, compared by a
  sha256 over each skill's own sorted relative paths and bytes: an unchanged skill plans `skip`,
  any other content or none yet plans `replace`/`add`); requirement 6's `configDigest` now also
  hashes every file under `skills/**`. "Pod manifests: export" requirement 1 gains the mirror
  write: `config/skills/` copied byte-for-byte into `skills/<name>/SKILL.md` per skill
  (`_export_skills`) — unlike a role or policy, a skill is not regenerated. `summarize_recipe`'s
  `skills` count (already landed by P31-1) is now backed by a real applied/exported scope, not
  just a derived number. See `agent-loop.spec.md` 1.24.0 for the prompt-composition and
  `skill`-tool side, `workspace-structure.spec.md` 1.14.0 for the on-disk scopes, and
  `cli-interface.spec.md` 1.52.0 / `cli-json-shapes.spec.md` 1.14.0 for `config explain`.

### Version 1.17.0 (2026-09-27)

- **P31-2: the operator's own recipes directory, and a listing (ADR 0013 §1 rules 4-5).**
  "Pod manifests: apply" requirement 8 gains a third resolution scope: `core.pod_apply.
  resolve_recipe` now checks a directory path, then the operator's own
  `config.user_recipes_dir()/<name>` (`DOCKET_HOME/recipes/<name>/`), then the shipped
  `config.recipes_dir()/<name>` — nearest wins by name — and its unresolvable-name error now
  names both scopes' recipe lists, not only the shipped one. New requirement 10, "Recipe
  listing": `core.pod_apply.list_recipes()`/`RecipeInfo` and the new `docket recipes list
  [--json]`/`docket recipes show <name|dir> [--json]` commands (`cli-interface.spec.md`), a
  read-only discovery surface over both scopes with no new writer.

### Version 1.16.0 (2026-09-27)

- **P31-4: five methodology recipes join the library (ADR 0013 §2).** New "The recipe library"
  section names the library's five `Methodology`-kind rows: `tdd`, `spec-first`, `reflexion`,
  `dual-review`, `frugal` (`templates/recipes/<name>/`), each a `pod.yaml` (`members`, and for
  `frugal` `settings`) plus a `pipeline.yaml` expressed only with the pipeline dialect that
  already exists. No `core/` module changed; `tdd`'s `check-red` command step is the first
  shipped use of an `on:` outcome map on a `run` step (`pipeline-format.spec.md`'s "Conditional
  steps and command steps").

### Version 1.15.0 (2026-09-27)

- **Four policy-pack recipes; `secure-build` and `ops-approval` on structured predicates
  (ADR 0013).** New "The recipe library" section: the twelve-recipe table by kind, and what a
  lean pod's `apply` plans for each. `git-safety`, `no-egress`, `secrets-guard` and
  `prod-approval` ship as `templates/recipes/<name>/` directories carrying `policies/` only (no
  `roles/`, no `pipeline.yaml`, no `members`) -- applying one changes no roster and no dispatch
  step. `secure-build/policies/require-approval-secret-writes.yaml` and
  `ops-approval/policies/ops-approval-high-risk.yaml` are rewritten (respectively) onto an
  `anyOf` of `{tool, path}` pairs plus a `matches`, and a `tool: bash` predicate beside their
  existing `matches`, so each fires on the call itself rather than free text alone.

### Version 1.14.0 (2026-09-27)

- **P31-1: a recipe says what it brings (ADR 0013 §1 rules 1-3).** New "Pod manifests: apply"
  requirement 9, "Recipe summary": `core.pod_apply.summarize_recipe(directory)` derives a
  directory's roles/policies/plugins/skills/members/settings counts and its bound pipeline's own
  `name`, shown by `docket validate`, `docket pod <p> apply`, and `docket init --recipe`/a
  discovered `.docket/` — never a declared `scope:` field, which stays refused as unknown.
  Requirement 1's manifest key set gains an optional `description` string, read-only display
  prose never applied to the pod; `export` (see "Pod manifests: export") cannot write it back,
  since nothing stores it on the pod. Requirement 6 is amended: `apply` now records
  `configSource`/`configDigest` after every plan it validated, an all-`skip` plan included, so
  composing a second, already-matching directory at another path still moves the record — only
  the `pod.apply` audit entry keeps its "only when something changed" rule.

### Version 1.13.0 (2026-09-27)

- **`docket pod <p> apply <name|dir>` resolves a shipped recipe by name.** "Pod manifests:
  apply" requirement 1: an argument that is not an existing directory resolves through the
  same `core.pod_apply.resolve_recipe` requirement 8 gives `docket init --recipe`, so the
  shipped recipes are reachable from an existing pod without a path into the installed
  package. Behaviour for a directory argument and for no argument is unchanged.

### Version 1.12.0 (2026-09-27)

- **P30-2: the pod records its configuration of record; `export` defaults to it (ADR 0012).**
  "Pod manifests: apply" requirement 6 now also records `configSource`/`configDigest` in the
  pod's settings after a successful `apply` (`core.pod_apply.directory_digest`, `PodSettings.
  RECORDED_KEYS`); neither field is ever written by `docket pod <p> config set` or carried in a
  `pod.yaml` `settings` mapping. "Pod manifests: export" requirements 1 and 3 now default *dir*
  to `<codebase>/.docket/`, matching `apply`; the non-empty refusal applies to that default too.
  `docket config explain <agent>` reports `configSource`, `configDigest`, and a recomputed
  `drift` (see `cli-interface.spec.md` 1.46.0 for the CLI-facing description).

### Version 1.11.0 (2026-09-27)

- **P30-1: `docket init` discovers, validates, and applies a repository's `.docket/`, or a
  `--recipe` (ADR 0012, D-46).** "Pod manifests: apply" gains requirement 8: a present
  `<location>/.docket/` is validated before provisioning and applied after, through the same
  `plan_apply`/`apply` this section already defines; `core/pod_apply.py` gains `resolve_recipe`
  for `--recipe <name|dir>`; `--recipe` and a present `.docket/` are mutually exclusive;
  `--no-apply` provisions only. Nothing but `init` and this section's `apply` ever reads
  `.docket/` — dispatch, serve, and schedules never do (ADR 0012 §2 rule 1).

### Version 1.10.0 (2026-09-26)

- **P28-8: export writes the short form, with a schema an editor can use.** "Pod manifests:
  export" requirement 1 now writes every role/policy/pod-manifest file in the short form
  (`core.archetypes.to_short_role`, `core.policy.to_short_policy`, the inverses of
  `normalize_role`/`normalize_policy`), each starting with a `# yaml-language-server:` header
  resolving against the four config-v1 JSON Schemas `export` now copies into the export's own
  `.schemas/`; a role's instructions move to a paired `<name>.md`; `pod.yaml` gains `kind: pod`
  and `name: <project>`. Requirement 4's round trip now compares a role/policy by parsed
  content, not raw text, since regenerating the short form no longer produces the same bytes a
  hand-authored or previously-applied file had.

### Version 1.9.0 (2026-09-26)

- **P27-10: `apply` writes a recipe's `policies/*.json` into the pod's own policy directory.**
  "Pod manifests: apply" requirement 1 adds `policies/*.json` to what is read; new requirement 3
  validates each file with `core.policy.validate_policy` (a bad file aborts the plan naming it,
  before any write) and writes it into `core.config.pod_config_dir(project)/policies/` — the same
  directory `core.policy.policy_files` reads and `export_pod` already copies from. Closes the
  round trip a P27-7 worker found broken: a recipe's optional policy pack previously had to be
  copied by hand into the fleet-wide `$POLICIES_DIR`, which `export` never wrote back out.

### Version 1.8.0 (2026-09-26)

- **P27-7: `docket pod <p> export <dir>`, the write direction of "Pod manifests: apply".** New
  "Pod manifests: export" section: `core/pod_apply.py::export_pod` writes this pod's own scope
  only — `roles/*.yaml` (pod-overlay entries via `RoleArchetype.to_wire()`), `policies/*.json`
  (this pod's own policy directory, copied as-is), a bound `pipeline.yaml` copy when one is set,
  and a `pod.yaml` naming non-Lead `members` and every non-default `setting` — into the same
  directory shape `apply` already reads, so a pod can be reproduced on a second machine. Global
  scope (the operator's own role overlay, fleet-wide policies, other pods) is never exported. The
  round trip (export → apply into a fresh pod → matching `config explain --json`) is the phase's
  integration proof.

### Version 1.7.0 (2026-09-26)

- **P27-9: `apply` writes to the pod's own role overlay, not the global one.** "Pod manifests:
  apply" requirement 2 corrects the workaround Version 1.6.0 recorded: `core/pod.py`'s roster
  helpers (`_role_names`, `parse_member_id`, `normalize_role`, `members_of`, `resolve_member`)
  now resolve a pod's own role overlay (`core.archetypes.load_registry(project)`), which they
  did not when P27-6 shipped, so a role `apply` wrote pod-scoped could be provisioned as a
  member but never resolved back out of `pod_full_roster`. `apply` now writes each recipe role
  into `core.config.pod_config_dir(project)/roles.json` (`core/pod_apply.py`'s `_plan_roles`
  treats `source_of(name) == f"pod:{project}"` as "already applied"), matching `docket roles add
  --pod <project>` and this command's own `<project>`-scoped surface; a role a recipe ships no
  longer leaks into the global overlay or into any other pod.

### Version 1.6.0 (2026-09-26)

- **P27-6: `docket pod <p> apply <dir>`.** New "Pod manifests: apply" section (ADR 0009):
  a recipe/manifest directory (`roles/*.yaml`, `pipeline.yaml`, a small `pod.yaml` naming
  `members`/`settings`/`pipeline`) applies to an existing pod in one command, composing the
  pre-existing `add_user_archetype`/member-provisioning/pipeline-bind/`PodSettings` writers
  (`core/pod_apply.py`) rather than the prior per-recipe manual command sequence. Roles land in
  the global user overlay, not a pod-scoped one — see the section for why. Additive and
  idempotent; validates fully before writing; `--dry-run` prints the plan only.

### Version 1.5.0 (2026-09-26)

- **P27-5: research/content/ops Lead steps name their own next role.** "Built-in blueprints"
  requirement 3 gains a step-`instructions` clause: each of the three pipelines' `lead` step now
  declares `instructions` naming that pod's real next role (Researcher/Writer/Operator) instead of
  inheriting the generic "plan for the Implementer" text the built-in `lead` archetype carries —
  made possible by `pipeline-format.spec.md` v2.6.0 removing the `role: lead` exemption on step
  `instructions`. `software` and `agentic-product` are unaffected and stay byte-identical.

### Version 1.4.0 (2026-09-21)

- Dispatch now resolves and runs a blueprint's `defaultPipeline` through `core/dispatch.py::effective_pipeline` (W36-C6); the Scope "known gap" note is closed. The 1.3.1 entry below describes the gap as it stood then.

### Version 1.3.1 (2026-09-19)

- Doc-truth pass, no behavior change. Replaced the stale "tracked as W-2/W-8" non-goal: the
  executor shipped, but nothing on the live dispatch path reads a blueprint's
  `defaultPipeline`. A non-software pod dispatched without `--file` runs only its Lead step, and
  this is now stated as a known gap (verified with `resolve_plan` against a research roster).
  Examples moved from the retired interactive `docket add --blueprint` flow to non-interactive
  `docket init`, with real `ui` prefixes. The CLI requirement no longer talks about prompts
  `init` does not issue. The user-authored note now says five built-ins, not four. The
  workspace-kind requirement now says which entry points reach `pod_work_dir`
  auto-provisioning.

### Version 1.3.0 (2026-08-20)

- Moved project and declarative blueprint provisioning to the canonical `docket init` surface;
  `docket add` now extends an existing pod instead of creating one.

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
