# Role Archetypes Specification

**Version**: 2.1.0
**Status**: Implemented. Four built-in and six starter archetypes ship; global and pod overlays
add or override roles; `deniedTools` is enforced by name and by capability on every turn.
**Last Updated**: 2026-10-23

## Purpose

This specification defines the **role archetype**: a versioned, declarative definition of a pod
role. A role's name, scope, model class, identity prose, gate contract, tool profile, tool
denylist, token budget and hop instruction are data. Built-in archetypes define the four software
roles (`lead`, `implementer`, `reviewer`, `tester`), a starter library ships six more
(`researcher`, `analyst`, `writer`, `critic`, `operator`, `monitor`), and an operator can define
or override an archetype with a YAML file (`docket pod update <file>`).

## Scope

This specification covers:

- The archetype schema: `name`, `version`, `scope`, `modelClass`, `soulTemplate`,
  `agentsTemplate`, `gateContract`, `toolProfile`, `tokenBudget`, `deniedTools`, and the
  optional `description`/`hopInstruction` fields; which are closed typed enums and which are
  open prose
- `deniedTools` and `registry_for_role`, the function that turns it into a narrowed
  `ToolRegistry` through the public `ToolRegistry.without()`/`without_kind()` API; the turn loop
  calling it once per turn is `agent-loop.spec.md`'s
- `hopInstruction` and `resolve_hop_instruction`, through which the Lead's and a custom role's
  hop message resolves its instruction text when a pipeline step declares none of its own; the
  hop-message builder is `pod-dispatch.spec.md`'s
- The built-in archetypes (lead/implementer/reviewer/tester) and their byte-identity guarantee
- The starter library (researcher/analyst/writer/critic/operator/monitor)
- The template rendering contract (`${var}` substitution, the guaranteed variable set)
- The global overlay (`~/.docket/docket-roles.json`), the pod overlay, and their merge rules
- How `modelClass` feeds the role→model policy (`model-profiles.spec.md`) without replacing it
- How pod member ids and role names (`normalize_role`, `member_id`, `pod_of`, `members_of`)
  resolve against this registry instead of a hardcoded list
- The `docket pod roles` CLI surface
- Shipped recipe bundles, as far as their role YAML is concerned: a recipe's role is an ordinary
  archetype document; a recipe's pipeline is `pipeline-format.spec.md`'s, its manifest and apply
  step are `pod-blueprints.spec.md`'s

This specification does NOT cover:

- Pod *composition* (which roles a pod has, duplicate-role indexing, the lean/full presets
  `DEFAULT_POD_ROLES`/`FULL_POD_ROLES`); see `workspace-structure.spec.md` and
  `docket-meta.spec.md`
- Pod blueprints (`docket init --blueprint`), which compose archetypes by name into a whole pod;
  see `pod-blueprints.spec.md`
- Gate *enforcement*: `resolve_gate`/`parse_verdict` and the mechanical/verdict/approval
  evaluation are `pod-dispatch.spec.md`'s "Generalized gate execution". This spec covers only the
  `gateContract` schema (the closed `kind` enum, `regexes`) and its agreement with the default
  pipeline's gates for the four built-in roles
- The role→model policy's own mechanics (rank anchors, presets, pinning, `docket setup model`);
  see `model-profiles.spec.md`
- The per-member runtime fields (`portRangeStart`, `scratchDir`, `verifyCmd`, …) in
  `.docket-meta.json`; see `docket-meta.spec.md`

## Requirements

### Archetype schema

1. A role archetype **MUST** carry: `name` (string), `version` (positive integer), `scope`,
   `modelClass`, `soulTemplate` (string), `agentsTemplate` (string), `gateContract`,
   `toolProfile` (string), and `tokenBudget` (positive integer; see "Context-compiler token
   budget"). `description`, `deniedTools` (see "Per-role tool sets") and `hopInstruction` (see
   "Hop instructions") **MAY** be present; empty or absent is valid for all three. `tokenBudget`
   **MAY** be absent from a wire document and defaults to `6000`, never a parse error.
   `deniedTools` absent or empty defaults to `()`: no narrower than the registry the caller hands
   in. `hopInstruction` absent or empty means "no declared instruction", not "no instruction at
   all". `from_wire` reads only the fields above; it refuses a `kind:` other than `role` and a
   `policyRole` key, and does not read any other key.
2. `scope` **MUST** be one of exactly `"org"` | `"pod"`, a closed enum. Every built-in and
   starter archetype is `"pod"`-scoped. `"org"` validates but nothing reads it: scope is shown by
   `docket pod roles` and changes no behaviour.
3. `modelClass` **MUST** be one of exactly `"cheap"` | `"strong"`, a closed enum, the same two
   classes the role→model policy uses.
4. `gateContract.kind` **MUST** be one of exactly `"none"` | `"verdict"` | `"mechanical"` |
   `"approval"`, a closed enum. Each `regexes` entry **MUST** compile as a regular expression.
   `regexes` is read only when `kind == "verdict"`; on another kind it is accepted and ignored.
   Each entry is a marker alternative: `resolve_gate` joins them into one `^\s*(A|B)\b`
   case-insensitive pattern whose first entry is the passing value, and a `verdict` contract
   with no `regexes` resolves to no gate. `parse_verdict` applies that pattern at the start of
   every non-blank line of the complete reply and accepts exactly one distinct marker (see
   `pipeline-format.spec.md` "Gates" requirement 3). See "Built-in archetypes and legacy
   fidelity" for the values the reviewer/tester archetypes carry.
5. There is no `editRights` field (ADR 0012 §2 rule 7). `deniedTools` is the archetype schema's
   only capability statement; nothing computes it from anything else. `editRights` gets no
   special handling anywhere (`docket pod validate` prints no note for it).
6. `name` **MUST** match `^[a-z][a-z0-9-]*$` (lowercase letters/digits/hyphens, starting with a
   letter). `version` **MUST** be a positive integer. `soulTemplate`/`agentsTemplate` **MUST NOT**
   be blank.
7. `toolProfile`, `description`, `hopInstruction` and `deniedTools` are open: any string is
   valid for the prose fields, and docket does not validate `deniedTools` entries against any
   live tool registry (a name absent from a given registry is a no-op removal; see "Per-role tool
   sets"). The closed sets are `scope`, `modelClass` and `gateContract.kind`, so docket can reason
   about them; `name` (which roles exist) and the prose fields are open.
8. An archetype definition that violates any of the above **MUST** be rejected with an error
   naming the offending field (`ArchetypeError`), never silently coerced or truncated to a valid
   value.

### Template rendering

1. `soulTemplate`/`agentsTemplate` **MUST** use `${identifier}` placeholders (Python's
   `string.Template` syntax), substituted strictly: a template referencing a variable that is not
   supplied at render time **MUST** raise `ArchetypeError` rather than emit a literal `${typo}` or
   drop text. Extra unused variables are allowed.
2. Every archetype **MUST** be able to rely on at least these variables at render time: `project`,
   `objective`, `codebase` (an empty string when no codebase is configured), and `workDir`.
   Provisioning also supplies `role`, `memberId`, `sessionKey`, `stack`, `codebaseOrConfigured`,
   `codebaseOrIt` and `requiredStartupFile` for every pod member; these are not part of the
   documented minimum. The built-in and starter templates use `project`, `objective`, `role`,
   `memberId`, `sessionKey` and `stack`.
3. `docket pod validate <file>` and `docket pod update <file>` **MUST** check a role document's
   structure (requirement 8 of "Archetype schema"). Neither renders the templates: an unknown
   variable passes both and fails when a member is provisioned from the archetype (requirement
   1). `validate_archetype_dict` performs the dry-run render against a representative variable
   set, but no command calls it (a known defect).

### Built-in archetypes and legacy fidelity

1. The four software roles (`lead`, `implementer`, `reviewer`, `tester`) **MUST** ship as
   built-in archetypes (`BUILTIN_ARCHETYPES`) whose rendered SOUL.md and AGENTS.md are
   **byte-identical** to a frozen, independently written baseline for any
   project/codebase/stack/description input. The parity test embeds that baseline and diffs it
   against the live renderer; it moves only with a deliberate, spec'd template change.
2. The four built-in archetypes resolve their model through their own name's row (see
   "Role→model policy integration"). Their `modelClass` **MUST** match that row's class
   (`lead`/`reviewer`/`tester` = cheap, `implementer` = strong). There is no `policyRole` field;
   a document that carries one is refused naming the key.
3. Their `gateContract` **MUST** match the role's real gate behaviour: `lead` = `none`,
   `implementer` = `mechanical` (the per-member `verifyCmd`, configured separately; see
   `docket-meta.spec.md`), `reviewer` = `verdict` with regexes `["APPROVE", "REQUEST-CHANGES"]`,
   `tester` = `verdict` with regexes `["PASS", "FAIL"]`. Each **MUST** equal (case-insensitively)
   the marker words `default_pipeline()` declares for that role's step and what `resolve_gate`
   resolves for a bare `role: reviewer`/`role: tester` step with no gate of its own; tests check
   that the three agree.
4. `normalize_role`, `member_id`, `pod_prefix`, `parse_member_id`, `pod_of` and `members_of`
   **MUST** keep the member-id shape `<project>-<role>[-N]` and sort a pod's members Lead first.
   `normalize_role` accepts only registered archetype names (case-insensitive, including the
   pod's own overlay when given); there is no input alias such as `programmer`.
5. A user-defined role name **MAY** end in another registered role's name (e.g.
   `security-reviewer`, ending in `reviewer`); the registry imposes no disjointness constraint.
   `pod_of` **MUST** still resolve such a member to its real pod: it reads the member's own
   recorded `.docket-meta.json` `pod` field first (see `pod-dispatch.spec.md` "Pipeline order and
   participation" requirement 3), falling back to id-string parsing only when that field is
   absent. `parse_member_id` receives an explicit project and only strips that project's prefix,
   so it is unaffected by the ambiguity.

### Generated instructions agree with the runtime contract

1. A built-in or starter archetype's `soulTemplate`/`agentsTemplate` **MUST NOT** instruct the
   model to make a private write it cannot make: telling it to write to `HEARTBEAT.md` or a
   `memory/` log. The live runtime contract (see `agent-loop.spec.md` requirement 30) tells the
   model every turn that private workspace state is read-only and that "Docket owns turn
   durability and no private logging is required"; generated prose asking for that write would
   contradict the contract composed into the same turn.
2. This does not apply to `WORKFLOW_AUTO.md`: its own `cd`/write-HEARTBEAT instructions are its
   documented manual-path contract, for an agent reading the file directly outside docket's turn
   loop. The turn loop never sends that raw file to the model (it projects a small read-only
   summary instead), and the file says so in a "Manual-path contract" paragraph right after its
   intro.
3. A test renders every built-in and starter archetype's SOUL/AGENTS templates and fails if any
   rendered line both asks to "write" and names `HEARTBEAT.md` or `memory/`: a check over the
   rendered prompt, not a grep over template source.
4. `POD_TEMPLATE_VERSION` **MUST** be bumped whenever a built-in or starter template's generated
   text changes. Each provisioned member records it as `templateVersion`; `docket setup` reports
   a member whose recorded version or rendered files differ from the current ones, and
   `docket pod update` with no argument re-renders it (see `workspace-structure.spec.md`).
5. **Prompt layers (ADR 0028 section 1).** A built-in or starter `soulTemplate`/`agentsTemplate`
   **MUST NOT** contain an absolute path (the codebase and working directory reach the model in
   the task message), `HEARTBEAT`, `memory/` or `promise`: nothing reads a completion promise,
   and a member's private files are read-only and off-limits to tools. Every `agentsTemplate`
   carries one shared `## Method` block of three bullets: start from what the task message
   delivers (the working directory, a repository map, what the previous step produced) and never
   re-read what it carries; find code with `grep` for a concrete name and `read` the lines needed,
   never listing the whole tree; and, to leave a note for later tasks, end the reply with
   `## Memory` and lines `- <kind>: <path or command> -- <fact>`, kind one of `generated`,
   `command`, `pitfall`, `convention`, facts only (workspace-structure.spec.md "Pod memory",
   requirement 3). The block stays under 520 characters. A step prompt adds only its own output
   contract. Both templates render to the same bytes for two tasks of one member, so the system
   prompt carries no task data. `POD_TEMPLATE_VERSION` is 5.

### Per-role tool sets

1. `deniedTools` (`denied_tools` on `RoleArchetype`) **MUST** be a tuple of built-in tool names
   (e.g. `"write"`, `"edit"`, `"bash"`, the names `builtin_registry()` registers) an archetype's
   agent may never call. It defaults to `()`.
2. `registry_for_role(base, role, project="")` **MUST** look *role* up in the live archetype
   registry (the pod's, when *project* is given) and return `base.without(*denied)`, the public
   `ToolRegistry.without()` API, never a private or parallel narrowing mechanism, further
   narrowed per requirement 6. An unrecognized *role* (empty string, a bare project id, any name
   absent from the registry), or one whose `denied_tools` is empty, with no pod-level denial
   (requirement 7) **MUST** return *base* unchanged.
3. No caller **MUST** branch on a role's name (e.g. `if role == "reviewer"`) to decide what to
   narrow: the denylist is data on the archetype, and `registry_for_role` is the single generic
   function every caller uses.
4. The four built-in archetypes' `denied_tools` **MUST** match their SOUL.md contract: `lead` and
   `reviewer` = `("write", "edit", "bash")` ("never edits code, runs git, or executes the build" /
   "read-only: no write/edit/exec"); `tester` = `("write", "edit")` (read-only, but keeps `bash`
   to run the suite it reports PASS/FAIL on); `implementer` = `()` (full-repo). See the
   "Built-in archetypes" table below.
5. `deniedTools` is the archetype schema's only capability statement ("Archetype schema"
   requirement 5); nothing else computes it or is computed from it.
6. **`registry_for_role` MUST also narrow by capability, not only by name.** A registry may
   contain tools whose name no `denied_tools` list can anticipate (an MCP-adapted tool, namespaced
   `mcp__<server>__<tool>`; see `mcp-client.spec.md` "Live-turn wiring"). After the name-based
   removal, `registry_for_role` **MUST** map every denied name through the fixed table
   `BUILTIN_TOOL_KINDS` (`read`/`glob`/`grep`/`fetch`/`skill`/`consult` → `read`, `write`/`edit`
   → `write`, `bash` → `exec`) and remove every remaining tool of those kinds through the public
   `ToolRegistry.without_kind()` API. The table is static, not read from *base*, so the denial
   depends only on the role's and pod's own data and survives a caller that already narrowed
   *base*. It **MUST NOT** be a per-role branch, an MCP-aware special case, or a second field on
   the archetype. Denying any one name therefore removes every tool of that name's kind: denying
   a `read`-kind name such as `fetch` also removes `read`, `glob`, `grep`, `skill` and `consult`
   (a known defect). For the shipped archetypes this step
   removes nothing beyond the name-based step from a builtins-only registry, because each denies
   only `write`-/`exec`-kind names and names all of them it denies; it removes an MCP tool of a
   denied kind.
7. **A pod also narrows every role's tools by its own `deniedTools` setting** (`PodSettings`;
   `pod-dispatch.spec.md` "Pod dispatch settings" item 8). `registry_for_role(base, role,
   project)` **MUST**, when *project* names a pod, take the union of that pod's `denied_tools`
   and *role*'s own before requirement 2's name-based removal and requirement 6's kind-based
   removal run. A pod-level denial is therefore as strong as an archetype-declared one: a
   `deniedTools` entry naming `fetch` **MUST** remove it from every role in that pod. An
   unreadable or malformed stored pod setting **MUST NOT** raise out of `registry_for_role`; it
   **MUST** degrade to "no additional pod-level denial" for that turn, because this function runs
   on every turn's live path and must never crash over a hand-edited settings file. The write
   path (`PodSettings.coerce`) refuses a bad value.
8. The implementer's and the writer's rendered `SOUL.md`, and the `bash` tool's schema description
   in `builtin_registry()`, **MUST** carry one sentence: create or change files with
   `write`/`edit`, not `cat >`, heredocs or `sed -i`; inspect with `read`/`grep`/`glob`; use `bash`
   to run things. This is guidance, not enforcement: `bash` stays available to both roles and its
   classification is unchanged.

### Hop instructions

1. `hopInstruction` **MUST** be open prose (like `toolProfile`/`description`), never validated
   against a template or the live tool registry. Empty or absent (the default) means "no declared
   instruction"; a gated role still gets one, per requirement 2.
2. `resolve_hop_instruction(archetype)` **MUST** return *archetype*'s own `hopInstruction` when
   non-empty; otherwise it **MUST** generate one from `gate_contract.kind`: a `verdict` role with
   `regexes` gets "Start exactly one output line with `<marker1>` or `<marker2>` (more joined by
   `or`) (case-insensitive)"; a `mechanical` role gets a generic "your work is verified
   mechanically before the pipeline advances"; an `approval` role gets a generic "a human must
   approve before the pipeline advances"; a `none` gate (or a `verdict` gate with no `regexes`)
   generates no instruction (`""`).
3. The `implementer`/`reviewer`/`tester` built-in archetypes' `hopInstruction` **MUST** remain
   unset: the hop-message builder never consults the registry for those three, and their hop
   messages are fixed built-in text regardless of this field. The `lead` archetype **MUST** carry
   a `hopInstruction` equal to "You are the pod Lead. Decompose this task into a concrete plan for
   the Implementer (you never edit code yourself):", and the builder's Lead branch **MUST**
   resolve it through `resolve_hop_instruction` like a custom role, so a global or pod overlay of
   `lead` changes the Lead's hop message. A pod with no `lead` overlay **MUST** see exactly that
   text. `resolve_hop_instruction` is reachable for `lead` and for any role the builder does not
   special-case; it is never reachable for `implementer`/`reviewer`/`tester`. A role absent from
   the registry gets no instruction.
4. A pipeline step's own `instructions` (see `pipeline-format.spec.md` "Steps") **MUST** take
   precedence over both an archetype's declared `hopInstruction` and the generated fallback, for
   any role the step targets, including `role: lead`: a step `{role: lead, instructions: "..."}`
   **MUST** replace the Lead's instruction text (built-in or overlaid) with the step's
   interpolated text.

### Starter library

1. Six starter archetypes **MUST** ship: `researcher`, `analyst`, `writer`, `critic`, `operator`,
   `monitor` (`STARTER_ARCHETYPES`). Each **MUST** pass `docket pod validate` and render both
   templates against a representative variable set without error.
2. Each starter archetype's model-policy key is its own name (see "Role→model policy
   integration").
3. A starter role can be provisioned into a live pod (e.g. `docket pod add researcher`) because
   `normalize_role`/`resolve_member` resolve against this registry. A preset roster composing
   several starter roles into one pod shape (e.g. `docket init --blueprint research`) is a pod
   blueprint; see `pod-blueprints.spec.md`, which uses this registry but is not defined here.

### Shipped recipes

1. Each shipped recipe **MUST** live in the wheel's recipe library (`templates/recipes/<name>/`
   inside the package), shipped by the same git-tracked-file inclusion as the baseline policies,
   with no separate packaging include list.
2. A recipe **MUST** carry a `README.md` naming its purpose and the command that applies it, and
   a `pod.yaml` (`pod-blueprints.spec.md` "Pod manifests: apply") naming the roles `apply` adds as
   members. A `pipeline.yaml` (this registry's roles referenced by name), a `roles/` directory, a
   `policies/` directory (`.yaml|yml|json`), a `skills/` directory and an `mcp-servers/` directory
   are each **optional**: a policy-pack recipe ships no pipeline, and a recipe whose roster is
   entirely built-in/starter archetypes ships no role YAML, since it would restate data this
   registry already has. An optional policy pack is read and applied by the apply step
   (`pod-blueprints.spec.md` "Pod manifests: apply" requirement 3).
3. A recipe's own role YAML **MUST** pass `docket pod validate` unmodified: a recipe is not a
   second archetype format; it is data consumed by the same `load_role_file`/`from_wire`/
   `add_user_archetype` this spec defines. Its `pipeline.yaml`, when present, **MUST** pass
   `docket pod validate` (`pipeline-format.spec.md`) and, once the roster its README describes is
   provisioned, **MUST** resolve with no skipped step (`resolve_plan`): a recipe that targets a
   role its own instructions never tell the operator to add is a defect in the recipe.
4. Applying a shipped recipe **MUST** be one command, `docket pod update <name|dir>`
   (`pod-blueprints.spec.md` "Pod manifests: apply"), which composes the role, member and
   pipeline-binding writers (a recipe's roles and policy pack land in the pod's own pod-scoped
   directories, never a global one). `docket pod update <file>` and `docket pod add <role>` remain
   valid for a partial or hand-tuned application. `docket pod recipes [<name>]` lists and shows
   the library (`pod-blueprints.spec.md`).
5. At least three recipes **MUST** ship: one gating an Implementer's change on a custom read-only
   reviewing role with a bounded rework cycle (`secure-build`), one over the research archetypes
   with a critic veto (`research-review`), and one gating an `operator` step on a human `approval`
   gate (`ops-approval`). Each **MUST** carry a test that loads it from the shipped library (not a
   hand-copied transcription) and validates it the way `docket pod validate` would.

### Role→model policy integration

1. An archetype's `modelClass` **MUST** slot into the existing role→model policy
   (`model-profiles.spec.md` "Roles and built-in policy") rather than replace it.
   `resolve_role_model` **MUST** first check the named policy table (`ALL_ROLES`/`role_models`,
   keyed by the archetype's own `name`); only when the role has no named entry there **MUST** it
   resolve through the archetype's `modelClass`, looked up in the member's pod registry, against
   the live rank anchors (`economy` for `cheap`, `standard` for `strong`). The named table holds
   all ten built-in and starter names with their classes from `ROLE_CLASS`, so for those ten the
   table decides and the archetype's `modelClass` is not read, including a global or pod overlay
   that reuses one of those names with a different `modelClass`.
2. This fallback **MUST NOT** add a hardcoded entry to `ALL_ROLES`/`ROLE_CLASS` per archetype:
   the archetype registry is the source of truth for any role beyond the ten named ones.
3. A role name present in neither the named policy table nor the pod's archetype registry
   **MUST** fall back to the model registry's own `default` (`docket-models.json` `default`,
   equal to the compiled-in default on a fresh install), never to the compiled-in literal while an
   operator has set another default.

### Context-compiler token budget

1. Every archetype **MUST** carry a `tokenBudget` (positive integer): the approximate number of
   tokens of prior-hop carryover the context compiler may thread into that role's hop prompt when
   the role is dispatched. It lives on the archetype rather than in a second registry: a role's
   resource budget is part of its declarative definition, like its gate contract.
2. `budget_for_role(role)` **MUST** resolve *role* against the live archetype registry and return
   its `tokenBudget`; a role absent from the registry **MUST** fall back to `DEFAULT_TOKEN_BUDGET`
   (`6000`) rather than raise or return zero. When the caller passes a model window
   (`context_window_tokens`, `max_output_tokens`), the fallback is the larger of `6000` and a
   share of that window; the live callers pass none.
3. A `tokenBudget` of zero or a negative value **MUST** be rejected by `RoleArchetype`'s own
   validation (`ArchetypeError`) for any archetype built through the constructor or `from_wire`.
   `tokenBudget` is an open positive integer, not a member of a closed set, but follows the same
   "reject, never coerce" rule.
4. `tokenBudget` **MUST NOT** be validated or interpreted as an exact token count from any real
   tokenizer: the context compiler's own approximation (bytes ÷ `CONTEXT_BYTES_PER_TOKEN`,
   default 4) consumes it. See `pod-dispatch.spec.md` "Bounded hop prompts" for how the budget is
   spent (the task description and the role's own instruction footer are reserved first; what is
   left funds the recency-weighted prior-hop carryover). The Lead's hop message is not budgeted.

### Pod-scoped token budgets

1. `budget_for_role(role, *, project="", ...)` **MUST** accept an optional `project`; when it is
   truthy, the role **MUST** resolve against that pod's registry (`load_registry(project)`, the
   same nearest-wins layering role resolution uses) and return the role's declared
   `tokenBudget`.
2. When `project=""` (the default), `load_registry()` with no argument is used, resolving only
   against built-ins, the starter library and the global overlay, never a pod.
3. Every live caller that dispatches a hop or compacts a session **MUST** pass its own `project`
   to `budget_for_role`. The two callers are the hop-message builder (each hop's budget during pod
   dispatch) and `compact_session` (session-history summarization). The agent loop **MUST** pass
   the turn's project to `compact_session`, its only call site on the live path.
4. A pod whose applied role archetype declares `tokenBudget: N` (via `docket pod update <file>`)
   **MUST** get `N` from `budget_for_role(role, project=<p>)`; a call without the project
   argument **MUST** return the global value, not the pod-scoped override.

### User registry overlay

1. User archetypes **MUST** overlay built-ins and the starter library via
   `~/.docket/docket-roles.json`, the same overlay pattern as `docket-models.json`: a top-level
   `roles:` map keyed by archetype name, read fresh on every access (not cached), silently
   skipping a malformed entry (never crashing a live fleet) rather than raising. No docket command
   writes this global file; the operator edits it by hand.
2. A user archetype **MUST** be able to both add a new role name and override an existing
   built-in/starter archetype by reusing its name ("user wins" by name). Overriding a built-in
   archetype is an explicit operator choice; the byte-identity guarantee (see "Built-in
   archetypes and legacy fidelity") applies to the out-of-the-box state with no overlay present.
3. The **authoring** format for an archetype **MUST** be a standalone YAML file
   (`docket pod update <file.yaml>`). The file is parsed, validated, and merged into the pod's
   JSON overlay (requirement 6) through docket's atomic read-modify-write for docket-owned JSON,
   the same boundary every other docket-owned registry file goes through.
4. docket's own built-in and starter archetypes **MUST NOT** be loaded from shipped template
   files: they are Python literals, matching the convention that workspace prose is generated
   inline. Only a user-authored archetype's *source* is a YAML file on disk.
5. Requirement 1's silent skip describes `load_registry` itself, which **MUST** keep resolving
   without raising or warning. Read-only and separate from that path, `docket setup` **MUST** run
   `find_overlay_problems` and report every overlay entry `load_registry` skipped (the role name
   and the `ArchetypeError` reason `from_wire` raised), or an unreadable/malformed overlay file
   itself, naming the file. It never edits the overlay.
6. A pod **MUST** be able to hold its own role overlay, layered above the global overlay for that
   pod alone: `$DOCKET_HOME/workspaces/pods/<pod>/config/roles.json` (`pod_config_dir(project)`),
   the same wire shape as `docket-roles.json`. `load_registry(project)` **MUST** resolve
   nearest-wins by name: the pod overlay above the global overlay, above the starter library,
   above built-ins; `load_registry()` with no project (or `project=""`) never reads a pod overlay.
   `registry_for_role`, SOUL.md/AGENTS.md rendering at provisioning, `normalize_role`, the role
   check `docket pod set pipeline <file>` and `docket pod update <dir>` run on a pipeline against
   the pod's roster, the
   custom-role hop-instruction lookup, `budget_for_role` and `resolve_role_model` **MUST**
   resolve through the calling turn's or member's own project, so a pod-scoped override is
   enforced on those paths, not only visible to `docket pod roles`. So is the gate fallback:
   dispatch, `docket run` and `docket pod plan` resolve a step's missing gate against the pod's
   registry, so a pod-only role's `gateContract` gates its step.
   `find_overlay_problems` **MUST** accept the same `project` and cover the pod file too,
   for `docket setup`.

### CLI surface

1. `docket pod roles [--json]` **MUST** show every registered archetype (built-in, starter, and
   user, including a user override of a built-in/starter name) with its source, scope, model
   class, gate contract kind, and one-line description. It **MUST NOT** show `editRights`.
   `--json` prints a list of `{name, source, scope, modelClass, gate, description}`.
2. `docket pod roles <name> [--json]` **MUST** print one archetype's full definition (YAML when
   PyYAML is available, JSON otherwise; `--json` adds `source` to the wire object) or exit 1 if
   `<name>` is not registered. Both forms resolve against the pod in scope (`--pod <p>`,
   `DOCKET_POD`, the pod whose codebase contains the cwd) layered above the global overlay, and
   report a pod-overlay-defined role's source as `pod:<p>`, distinct from `user`; outside any pod
   they see the global registry. Source is one of `built-in`, `starter`, `user`, `pod:<p>`.
3. `docket pod update <file.yaml>` **MUST** validate the file's archetype definition (a `kind:
   role` document, or one whose location names the kind, such as a file under `roles/`) and, on
   success, merge it into that pod's own overlay and write a `pod.apply` audit entry; on failure
   it **MUST** report the invalid field and make no change to the overlay file.
4. `docket pod validate <file.yaml>` **MUST** validate that file's definition without persisting
   it (a dry run ahead of `docket pod update`), with the same structural checks and no template
   render (see "Template rendering" requirement 3).

## Interface Contracts

### CLI Command Signatures

```text
docket pod roles [<name>] [--json] [--pod <p>]
docket pod update <file.yaml>
docket pod validate <file.yaml>
```

### Wire format (a user archetype YAML file)

```yaml
kind: role
name: producer
version: 1
scope: pod
modelClass: cheap
toolProfile: content-ops
description: coordinates content production across writer/critic
tokenBudget: 6000
deniedTools: []   # optional; e.g. ["write", "edit", "bash"] for a read-only role
hopInstruction: ""   # optional; unset + a gated role -> generated from gateContract
gateContract:
  kind: none
soulTemplate: |
  # SOUL.md — ${project} · ${role}

  ## Identity
  You are the **${role}** of the **${project}** pod.

  ## Objective
  ${objective}
agentsTemplate: |
  # AGENTS.md — ${project} · ${role}

  ## Red Lines
  Stay within the `${project}` pod.
```

A file outside a `roles/` directory needs `kind: role` for `docket pod update <file>` and
`docket pod validate` to recognise it; `from_wire` accepts and strips it.

A second, short form is also accepted, by `docket pod update <file>`, `docket pod validate` and
`docket pod update <dir>`. `load_role_file` detects it (the presence of any of
`cannot`/`verdict`/`verify`/`approval`/`instructions`/`model`, or an explicit `kind: role` with
none of the canonical-only keys) and normalizes it into the canonical form above
(`normalize_role`) before `from_wire` sees it. A document carrying any canonical-only key
(`modelClass`, `deniedTools`, `gateContract`, `soulTemplate`, `agentsTemplate`) is canonical and
passes through unchanged whatever its `kind:` says, so a `docket pod roles` dump with `kind: role`
added loads as written; `kind: role` is accepted and stripped either way. A document mixing a
short-form key with a canonical-only key **MUST** be refused naming both sets of keys, never
normalized with the canonical keys silently dropped. An unknown key in a short-form document is
refused.

```yaml
kind: role
name: security-vetter
model: strong                        # cheap | strong -- a model id is rejected, naming
                                      # `docket setup model set security-vetter <id>` instead
description: read-only security pass over the implementer's change
cannot: [write, edit, bash]          # -> deniedTools; the sole capability statement
verdict: [APPROVE, REQUEST-CHANGES]  # or verify: true | approval: true | omitted (-> gateContract
                                      # kind none); more than one of the three is an error
instructions: security-vetter.md     # optional; default "<name>.md" beside this YAML file
```

`instructions` names a Markdown file (resolved relative to the short-form YAML's own directory)
whose content up to an optional literal `## AGENTS` heading line becomes `soulTemplate`; the text
after that heading becomes `agentsTemplate`, or the starter library's AGENTS prose when the
heading is absent. The same `${variable}` substitution applies to both halves at render time.
`scope`, `version`, `tokenBudget`, `toolProfile` and `hopInstruction` may be given; `scope`
defaults to `"pod"`, `version` to `1`, `tokenBudget` to `6000`, the same defaults `from_wire`
applies to the canonical form.

### Built-in archetypes

| Name | Scope | modelClass | gateContract | tokenBudget | deniedTools |
| --- | --- | --- | --- | --- | --- |
| `lead` | pod | cheap | none | 2000 | write, edit, bash |
| `implementer` | pod | strong | mechanical | 8000 | *(none)* |
| `reviewer` | pod | cheap | verdict (APPROVE\|REQUEST-CHANGES) | 6000 | write, edit, bash |
| `tester` | pod | cheap | verdict (PASS\|FAIL) | 4000 | write, edit |

### Starter archetypes

`modelClass` is the archetype's own value. The model a starter role runs on comes from its named
policy row ("Role→model policy integration" requirement 1), whose class is shown in the last
column; `analyst` and `critic` disagree (a known defect).

| Name | Scope | modelClass | gateContract | tokenBudget | deniedTools | Policy row class |
| --- | --- | --- | --- | --- | --- | --- |
| `researcher` | pod | strong | none | 8000 | *(none)* | strong |
| `analyst` | pod | strong | none | 8000 | *(none)* | cheap |
| `writer` | pod | cheap | none | 6000 | *(none)* | cheap |
| `critic` | pod | cheap | verdict (APPROVE\|REJECT) | 6000 | write, edit, bash | strong |
| `operator` | pod | strong | mechanical | 8000 | *(none)* | strong |
| `monitor` | pod | cheap | approval | 4000 | write, edit, bash | cheap |

### Overlay files

- Global: `~/.docket/docket-roles.json`
- Pod: `$DOCKET_HOME/workspaces/pods/<pod>/config/roles.json`
- Shape (both): `{"roles": {"<name>": {<archetype fields, camelCase>}}}`

### Return Codes

- `0`: success (listed/shown/applied/validated cleanly)
- `1`: a `docket pod roles <name>`, `docket pod update` or `docket pod validate` target not
  found or invalid, a malformed archetype definition, or no pod resolved for `docket pod update`
- `2`: a usage error (unknown option, missing argument)

## Examples

### Listing and inspecting archetypes

```bash
docket pod roles
docket pod roles reviewer
```

### Applying a custom archetype

```bash
docket pod update ./producer.yaml
# Applied role 'producer' to pod 'myapp'.
```

### Validating before applying

```bash
docket pod validate ./producer.yaml
```

## Validation

### Pre-conditions

- `~/.docket/` exists (created by the first `docket init`); `docket pod update` creates the pod
  overlay file's parent directory if needed

### Post-conditions

- `docket pod update <file>` on a valid file leaves exactly one archetype added or overridden in
  the pod's `roles.json` `roles:` map; no other key in that file is touched
- The four built-in archetypes' rendered SOUL.md/AGENTS.md remain byte-identical to the frozen
  baseline for any input, with no overlay present

### Invariants

- `scope`, `modelClass` and `gateContract.kind` are always one of their closed enum's values for
  every archetype the registry returns: `load_registry()` never returns an archetype that would
  fail its own validation
- A key outside the archetype schema never fails a canonical `from_wire` load (except `kind:`
  other than `role` and `policyRole`) and never resurfaces from `to_wire()`
- A malformed overlay entry never prevents the rest of the registry (built-ins, starter library,
  other overlay entries) from loading
- A shipped recipe's role YAML carries no exemption from `from_wire`: a recipe that could not pass
  `docket pod update` if hand-copied is a broken recipe, not a special case

## Implementation

- `src/docket/core/archetypes.py`: `RoleArchetype`, `GateContract`, `ArchetypeError`,
  `from_wire`, `to_wire`, `SCOPES`, `MODEL_CLASSES`, `GATE_KINDS`, `render`,
  `resolve_hop_instruction`, `BUILTIN_ARCHETYPES`, `BUILTIN_ROLE_ORDER`, `STARTER_ARCHETYPES`,
  `STARTER_ROLE_ORDER`, `ArchetypeRegistry` (`source_of`), `load_registry`,
  `find_overlay_problems`, `BUILTIN_TOOL_KINDS`, `registry_for_role`, `validate_archetype_dict`,
  `parse_yaml_file`, `normalize_role` (short form), `to_short_role`, `load_role_file`,
  `add_user_archetype`
- `src/docket/core/tools.py`: `ToolRegistry.without`, `ToolRegistry.without_kind`, `Tool.kind`,
  `builtin_registry` (the `bash` description sentence)
- `src/docket/core/pod.py`: `normalize_role`, `member_id`, `pod_prefix`, `pod_of`, `members_of`,
  `parse_member_id`, `resolve_member`, `DEFAULT_POD_ROLES`, `FULL_POD_ROLES`, `PodSettings`
  (`deniedTools`, `coerce`, `load_for`)
- `src/docket/core/pod_provisioning.py`: `POD_TEMPLATE_VERSION`, the member render context
  (`_render_context`), SOUL.md/AGENTS.md rendering
- `src/docket/core/orchestrator.py`: `resolve_gate`, `parse_verdict`, `resolve_plan`
- `src/docket/core/pipeline.py`: `default_pipeline`
- `src/docket/core/dispatch.py`: the hop-message builder (`_hop_message`,
  `_resolve_hop_instructions`); plan resolution for dispatch (`_resolve_pipeline_steps`)
- `src/docket/core/context.py`: `budget_for_role`, `DEFAULT_TOKEN_BUDGET`
- `src/docket/core/session.py`: `compact_session`
- `src/docket/core/agent_loop.py`: the per-turn `registry_for_role` call; the compaction call
  passing the turn's project
- `src/docket/core/models_policy.py`: `resolve_role_model`, `ALL_ROLES`, `ROLE_CLASS`,
  `rank_anchors`
- `src/docket/core/identity.py`: the live runtime startup contract
- `src/docket/core/memory.py`: `seed_contract` (the `WORKFLOW_AUTO.md` manual-path paragraph),
  `REQUIRED_STARTUP_FILE`
- `src/docket/core/config_docs.py`: `load_document` (role kind detection and validation)
- `src/docket/core/pod_apply.py`: directory and recipe apply
- `src/docket/cli/_pod_config.py`: `docket pod roles`, `docket pod update`, `docket pod validate`,
  `docket pod recipes`, `docket pod plan`
- `src/docket/cli/_pod.py`: `docket pod add`, the `docket pod set pipeline` role check against the pod roster
- `src/docket/cli/_run.py`: `docket run` plan resolution
- `src/docket/cli/_setup_check.py`: overlay problem and stale-template reports for `docket setup`
- `src/docket/config.py`: `ARCHETYPE_REGISTRY_FILE`, `pod_config_dir`, `recipes_dir`
- `src/docket/templates/recipes/`: the shipped recipe library
- Tests: `tests/integration/test_pod_role_workspace_parity.py` (byte identity),
  `tests/integration/test_archetypes.py` and `tests/unit/core/test_pipeline__spec.py` (gate
  agreement), `tests/unit/core/test_archetypes.py` (runtime-contract and prompt-layer checks,
  overlay problems, pod `deniedTools`), `tests/integration/test_role_tools_and_identity.py`
  (`BUILTIN_TOOL_KINDS` pinned against `builtin_registry()`), `tests/integration/test_recipes.py`
