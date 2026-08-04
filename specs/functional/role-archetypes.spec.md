# Role Archetypes Specification

**Version**: 1.4.0
**Status**: Implemented. `gateContract` is now load-bearing (ROADMAP Phase 16 W-8): the dispatch
executor (`core/orchestrator.py`) resolves it as a step's gate fallback — see
`pod-dispatch.spec.md`'s "Generalized gate execution". Archetypes are also composed by name into
pod blueprints (Phase 16 W-7; see `pod-blueprints.spec.md`). ROADMAP Phase 17's C-1 (the context
compiler) added a `tokenBudget` field — see "Archetype schema" and "Context-compiler token
budget" below. ROADMAP Phase 19's P19-12 added `deniedTools` — see "Archetype schema" and the new
"Per-role tool sets" section — and, unlike `editRights`, it is genuinely *enforced*:
`core.archetypes.registry_for_role` is called by `core/agent_loop.py` once per turn to remove
those tool names from the registry the model is given, so a denied tool is unreachable, not just
discouraged. See `agent-loop.spec.md` for how the turn loop consumes it.
**Last Updated**: 2026-08-02

## Purpose

This specification defines the **role archetype**: a versioned, declarative definition of a pod
role (`core/archetypes.py`). Before ROADMAP Phase 16 W-6, a pod role was a closed 4-tuple
(`lead`/`implementer`/`reviewer`/`tester`) hardcoded in `core/pod.py`, and every role's identity
prose (SOUL.md/AGENTS.md) was hand-written Python string-building in `cli/_pod.py`. A fifth role
was inexpressible without editing both files. This spec documents the registry that replaced
that closed set: a role's name, scope, model class, identity prose, gate contract, edit rights,
and tool profile are now data — built-in archetypes reproduce the four legacy roles
byte-identical, a starter library ships six more (`researcher`, `analyst`, `writer`, `critic`,
`operator`, `monitor`), and a user can define or override an archetype via a YAML file
(`docket roles add`).

## Scope

This specification covers:

- The archetype schema: `name`, `version`, `scope`, `modelClass`, `soulTemplate`,
  `agentsTemplate`, `gateContract`, `editRights`, `toolProfile`, `deniedTools`, and the optional
  `policyRole`/`description` fields — which are closed typed enums and which are open prose
- The `deniedTools` field and `registry_for_role`, the one function that turns it into an
  actually-narrowed `ToolRegistry` via the public `ToolRegistry.without()` API (ROADMAP Phase 19
  P19-12) — this spec documents the data and that function's contract; `agent-loop.spec.md`
  documents that `core/agent_loop.py` calls it once per turn
- The built-in archetypes (lead/implementer/reviewer/tester) and their byte-identical-to-legacy
  guarantee
- The starter library (researcher/analyst/writer/critic/operator/monitor)
- The template rendering contract (`${var}`-style substitution, the guaranteed variable set)
- The user-overlay registry (`~/.openclaw/docket-roles.json`) and its merge/override semantics
- How `modelClass` integrates with the existing role→model policy (`model-profiles.spec.md`)
  without replacing it
- How `core/pod.py`'s `normalize_role`/`member_id`/`pod_of`/`members_of`/`POD_ROLES`/
  `POD_ROLE_POLICY` resolve against this registry instead of a hardcoded list
- The `docket roles list/show/add/validate` CLI surface

This specification does NOT cover:

- Pod *composition* (which roles a given pod actually has, duplicate-role indexing, the
  lean/full presets) — that remains `core/pod.py`'s `plan_pod`/`DEFAULT_POD_ROLES`/
  `FULL_POD_ROLES`, unchanged by this spec; see `workspace-structure.spec.md` and
  `docket-meta.spec.md`
- Named pod *rosters/blueprints* (`docket add --blueprint`) that let `docket add` compose a
  non-default set of archetypes for a whole pod in one step — shipped as ROADMAP Phase 16 W-7;
  see `pod-blueprints.spec.md`
- The dispatch executor's actual gate *enforcement* — `core.orchestrator.resolve_gate`/
  `parse_verdict` and the generic mechanical/verdict/approval evaluation loop are documented in
  `pod-dispatch.spec.md`'s "Generalized gate execution" (ROADMAP Phase 16 W-8, shipped). This spec
  covers only the `gateContract` *schema* itself (the closed `kind` enum, `regexes`) and that it
  is validated to match `core/pipeline.py`'s `default_pipeline()` gates for the four legacy roles
  — see Requirements — not how the executor consumes it
- The role→model policy's resolution mechanics themselves (rank anchors, presets, pinning,
  `docket models`) — see `model-profiles.spec.md`; this spec only covers how an archetype's
  `modelClass` feeds into that existing system
- The per-member runtime fields (`portRangeStart`, `scratchDir`, `verifyCmd`, …) written to
  `.docket-meta.json` — see `docket-meta.spec.md`

## Requirements

### Archetype schema

1. A role archetype **MUST** carry: `name` (string), `version` (positive integer), `scope`,
   `modelClass`, `soulTemplate` (string), `agentsTemplate` (string), `gateContract`,
   `editRights`, `toolProfile` (string), and `tokenBudget` (positive integer — ROADMAP Phase 17
   C-1; see "Context-compiler token budget" below). `policyRole`, `description`, and
   `deniedTools` (ROADMAP Phase 19 P19-12; see "Per-role tool sets" below) **MAY** be present
   (empty/absent is valid for all three); `tokenBudget` **MAY** be absent from a wire document
   (a pre-C-1 user overlay entry, or a hand-authored YAML file that predates this field) and
   defaults to `6000` when omitted — never a parse error. `deniedTools` absent/empty defaults to
   `()` — no narrower than whatever registry the caller hands in.
2. `scope` **MUST** be one of exactly `"org"` | `"pod"` — a closed enum. Every built-in and
   starter-library archetype shipped today is `"pod"`-scoped (org-scoped archetypes are a valid,
   validated value in the type system, reserved for a future card; none ship yet).
3. `modelClass` **MUST** be one of exactly `"cheap"` | `"strong"` — a closed enum, matching the
   two classes `model-profiles.spec.md`'s `ROLE_CLASS` already uses.
4. `gateContract.kind` **MUST** be one of exactly `"none"` | `"verdict"` | `"mechanical"` |
   `"approval"` — a closed enum. `regexes` (a list of strings, each a valid regular expression)
   **MUST** be present only when `kind == "verdict"`; each entry is a marker alternative matched
   against the first non-blank line of a reply, mirroring `core/dispatch.py`'s existing
   Reviewer/Tester verdict-parsing convention (`^\s*(A|B)\b`, case-insensitive) — see "Legacy
   archetype fidelity" below for the exact values the reviewer/tester archetypes carry.
5. `editRights` **MUST** be one of exactly `"none"` | `"read-only"` | `"write"` — a closed enum.
   `editRights` itself remains descriptive metadata, by design — it is not mechanically derived
   into a tool denylist, because the mapping is not one-to-one (the `tester` archetype is
   `"read-only"` yet keeps `bash`, since observing behaviour requires running it; see "Per-role
   tool sets" below). The genuinely-enforced counterpart is the separate `deniedTools` field —
   an archetype author declares both independently, and nothing in this schema computes one from
   the other.
6. `name` **MUST** match `^[a-z][a-z0-9-]*$` (lowercase letters/digits/hyphens, starting with a
   letter). `version` **MUST** be a positive integer. `soulTemplate`/`agentsTemplate` **MUST NOT**
   be blank.
7. `toolProfile`, `description`, and `deniedTools` are open — any non-empty (for `toolProfile`)
   or any (for `description`, including empty) string is valid for the two prose fields; docket
   does not validate `deniedTools`' entries against any live tool registry (a name that does not
   exist in a given registry is simply a no-op removal — see "Per-role tool sets"). Per ROADMAP
   Phase 16's explicit anti-overengineering rule: "archetype prose and rosters are
   user-extensible, but gate contracts, edit rights, and scope stay closed typed sets docket can
   reason about" — `scope`, `modelClass`, `gateContract.kind`, and `editRights` are the closed
   sets; `name` (which roles exist), `soulTemplate`, `agentsTemplate`, `toolProfile`,
   `description`, and `deniedTools` are open.
8. An archetype definition that violates any of the above **MUST** be rejected with a clear error
   naming the offending field (`ArchetypeError`) — never silently coerced or truncated to a valid
   value.

### Template rendering

1. `soulTemplate`/`agentsTemplate` **MUST** use `${identifier}`-style placeholders (Python's
   `string.Template` syntax), substituted strictly: a template referencing a variable that is not
   supplied at render time **MUST** raise a clear error rather than emit a literal
   `${typo}`/silently drop text.
2. Every archetype **MUST** be able to rely on at least these variables at render time: `project`,
   `objective`, `codebase` (may be an empty string when no codebase is configured — the schema's
   "codebase?" optionality), and `workDir`. Docket's own built-in/starter archetypes additionally
   rely on `role`, `memberId`, `sessionKey`, `stack`, `codebaseOrConfigured`, `codebaseOrIt`, and
   `requiredStartupFile` — supplied by `cli/_pod.py`'s renderer for every pod member, but not part
   of the publicly documented minimum a user archetype is guaranteed.
3. `docket roles validate` **MUST** dry-run render both templates against a representative sample
   variable set and report any unknown-variable error, so an authoring mistake is caught before
   `docket roles add` persists it (or, for a live registry entry, is caught by an operator
   proactively).

### Built-in archetypes and legacy fidelity

1. The four legacy pod roles (`lead`, `implementer`, `reviewer`, `tester`) **MUST** ship as
   built-in archetypes (`core/archetypes.py`'s `BUILTIN_ARCHETYPES`) whose rendered SOUL.md and
   AGENTS.md are **byte-identical** to the pre-W-6 hand-written generators, for any
   project/codebase/stack/description input. This is enforced by
   `tests/python/test_legacy_role_parity.py`, which embeds a frozen, independent copy of the
   pre-W-6 generator functions and diffs them against the live archetype-driven renderer.
2. The four legacy archetypes **MUST** carry a `policyRole` override equal to their historical
   policy-table row (`lead`→`manager`, `implementer`→`programmer`, `reviewer`→`reviewer`,
   `tester`→`tester`) — see "Role→model policy integration" below. Their `modelClass` **MUST**
   match that row's existing class (`manager`/`reviewer`/`tester` = cheap, `programmer` = strong).
3. Their `gateContract` **MUST** match this role's real gate behavior: `lead` = `none`,
   `implementer` = `mechanical` (the per-member `verifyCmd`, configured separately — see
   `docket-meta.spec.md`), `reviewer` = `verdict` with regexes `["APPROVE", "REQUEST-CHANGES"]`,
   `tester` = `verdict` with regexes `["PASS", "FAIL"]` — each byte-equal (case-insensitively; see
   `pod-dispatch.spec.md`'s "Generalized gate execution") to the marker words
   `core/pipeline.py`'s `default_pipeline()` declares for that role's step, and to what
   `core.orchestrator.resolve_gate` resolves for a bare `role: reviewer`/`role: tester` step with
   no gate of its own — all three (this registry, the pipeline format's hardcoded default, and
   the executor's own fallback resolution) verified to agree by test
   (`tests/python/test_archetypes.py`, `tests/python/test_pipeline_spec.py`). Before W-8,
   this cross-check was against a now-deleted `core/dispatch.py`-private regex constant
   (`_REVIEWER_VERDICT_RE`/`_TESTER_VERDICT_RE`) — gate execution reads this registry (or the
   pipeline format) directly now, so that private copy no longer exists to drift from.
4. `core/pod.py`'s `normalize_role`, `member_id`, `pod_prefix`, `parse_member_id`, `pod_of`, and
   `members_of` **MUST** produce identical results for the four legacy roles as before this
   registry existed — same accepted role strings (including the `programmer` → `implementer`
   alias), same member-id shape (`<project>-<role>[-N]`), same sort order (Lead first).

### Per-role tool sets (ROADMAP Phase 19 P19-12)

1. `denied_tools` **MUST** be a tuple of built-in tool names (e.g. `"write"`, `"edit"`, `"bash"` —
   `core.tools.builtin_registry()`'s names) an archetype's agent may never call. It defaults to
   `()` for any archetype that does not declare one.
2. `core.archetypes.registry_for_role(base, role)` **MUST** look *role* up in the live archetype
   registry and, when found with a non-empty `denied_tools`, return
   `base.without(*archetype.denied_tools)` — the public `ToolRegistry.without()` API, never a
   private/parallel narrowing mechanism. An unrecognized *role* (empty string, a bare project id,
   any name absent from the registry) or one whose `denied_tools` is empty **MUST** return *base*
   unchanged.
3. No caller **MUST** branch on a role's name (e.g. `if role == "reviewer"`) to decide what to
   narrow — the denylist is data on the archetype; `registry_for_role` is the single, generic
   function every caller uses.
4. The four legacy archetypes' `denied_tools` **MUST** match their documented SOUL.md contract:
   `lead` and `reviewer` = `("write", "edit", "bash")` ("never edits code, runs git, or executes
   the build" / "read-only: no write/edit/exec"); `tester` = `("write", "edit")` (read-only, but
   keeps `bash` — it must actually run the test suite it reports PASS/FAIL on); `implementer` =
   `()` (full-repo). See "Built-in archetypes" below for the full table.
5. This field is independent of `editRights` (requirement 5 under "Archetype schema") — a user
   archetype **MAY** set any combination of the two; nothing computes one from the other.

### Starter library

1. Six starter archetypes **MUST** ship: `researcher`, `analyst`, `writer`, `critic`, `operator`,
   `monitor` (`core/archetypes.py`'s `STARTER_ARCHETYPES`). Each **MUST** pass
   `docket roles validate` (structural validation + a dry-run template render).
2. None of the starter archetypes carries a `policyRole` override — each resolves through its own
   name as the policy-role key (see "Role→model policy integration").
3. Provisioning a starter role into a live pod (e.g. `docket pod <project> add researcher`) works
   because `normalize_role`/`resolve_member` resolve against this registry. A *preset roster*
   composing several starter roles into one pod shape in a single command (e.g. a `research pod`
   of Lead + Researcher + Analyst + Writer + Critic) is a **pod blueprint** — see the separate
   `pod-blueprints.spec.md` (ROADMAP Phase 16 W-7), which this spec's registry is a building block
   for but does not itself define.

### Role→model policy integration

1. An archetype's `modelClass` **MUST** slot into the *existing* role→model policy
   (`model-profiles.spec.md`) rather than replace it. Resolution
   (`models_policy.resolve_role_model`) **MUST** first check the named policy table
   (`ALL_ROLES`/`role_models`, keyed by `resolvedPolicyRole` — the archetype's `policyRole` if
   set, else its own `name`); if the role is not a named entry there, it **MUST** fall back to
   resolving via the archetype's own `modelClass` against the live rank anchors (`economy` for
   `cheap`, `standard` for `strong`) rather than collapsing to the global default model
   unconditionally.
2. This fallback **MUST NOT** add a new hardcoded entry to `model-profiles.spec.md`'s
   `ALL_ROLES`/`ROLE_CLASS` table per archetype — the archetype registry itself is the source of
   truth for any role beyond the pre-existing named ones.
3. A totally unknown role name (present in neither the named policy table nor the archetype
   registry) **MUST** fall back to `cfg.DEFAULT_MODEL`, unchanged from pre-W-6 behavior.

### Context-compiler token budget (ROADMAP Phase 17 C-1)

1. Every archetype **MUST** carry a `tokenBudget` (positive integer) — the (approximate) number
   of tokens of prior-hop carryover `core/context.py`'s compiler (`compile_artifact`/
   `hop_share`) may thread into that role's hop prompt when the role is dispatched via
   `core/dispatch.py`'s `_hop_message`. This lives on the archetype rather than in a second,
   parallel registry: a role's resource budget is part of its declarative definition, the same as
   its gate contract or edit rights.
2. `core/context.py`'s `budget_for_role(role)` **MUST** resolve *role* against the live archetype
   registry (`core/archetypes.py.load_registry()`) and return its `tokenBudget`; a role absent
   from the registry, or one whose `tokenBudget` is non-positive, **MUST** fall back to a fixed
   default (`context.DEFAULT_TOKEN_BUDGET`, `6000`) rather than raise or silently return zero.
3. A `tokenBudget` of zero or a negative value **MUST** be rejected by `RoleArchetype.__post_init__`
   (`ArchetypeError`) for any archetype built through the normal constructor path or `from_wire` —
   the same closed-validation treatment `version` already gets. This is orthogonal to the
   scope/modelClass/gateContract/editRights closed *enums* (`tokenBudget` is an open positive
   integer, not a member of a fixed value set) but follows the same "reject, never coerce" rule.
4. `tokenBudget` **MUST NOT** be validated or interpreted as an exact token count from any real
   model tokenizer — `core/context.py`'s own approximation (bytes ÷ `config.
   CONTEXT_BYTES_PER_TOKEN`, default 4) is what actually consumes this value. See
   `pod-dispatch.spec.md`'s "Bounded hop prompts" for how the budget is spent once resolved (the
   task description and the role's own instruction footer are reserved first; what's left funds
   the recency-weighted prior-hop carryover).

### User registry overlay

1. User archetypes **MUST** overlay built-ins and the starter library via
   `~/.openclaw/docket-roles.json` — the same overlay pattern `model-profiles.spec.md`'s
   `docket-models.json` uses: a top-level `roles:` map keyed by archetype name, read fresh on
   every access (not cached), silently skipping a malformed entry (never crashing a live fleet)
   rather than raising.
2. A user archetype **MUST** be able to both add a brand-new role name and override an existing
   built-in/starter archetype by reusing its name — "user wins" by name, exactly as
   `docket-models.json`'s per-role model overrides work. Overriding a legacy archetype
   (lead/implementer/reviewer/tester) is an explicit operator choice; the byte-identical
   guarantee (see "Built-in archetypes and legacy fidelity") applies to the out-of-the-box state
   with no user overlay present, not to a fleet a user has deliberately customized.
3. The **authoring** format for a new archetype **MUST** be a standalone YAML file (`docket roles
   add <file.yaml>`) — "a role becomes a versioned YAML definition." The file is parsed,
   validated, and merged into the JSON-backed overlay via `edges/store.py`'s atomic
   read-modify-write (docket's D-12 single-writer chokepoint for docket-owned JSON) — the same
   boundary every other docket-owned registry file goes through.
4. Docket's own built-in and starter archetypes **MUST NOT** be loaded from shipped template
   files — they are Python literals in `core/archetypes.py`, matching this project's standing
   convention that workspace prose is generated inline in Python (see `CLAUDE.md`'s `templates/`
   note). Only a user-authored archetype's *source* is a YAML file on disk.

### CLI surface

1. `docket roles list` **MUST** show every registered archetype (built-in, starter, and user —
   including a user override of a built-in/starter name) with its scope, model class, gate
   contract kind, edit rights, and one-line description.
2. `docket roles show <name>` **MUST** print one archetype's full definition (YAML when PyYAML
   is available, JSON otherwise) or fail with a non-zero exit if `<name>` is not registered.
3. `docket roles add <file.yaml>` **MUST** validate the file's archetype definition and, on
   success, merge it into the user overlay; on failure it **MUST** report the specific invalid
   field(s) and make no change to the overlay file.
4. `docket roles validate [file.yaml]` **MUST**, with no argument, validate every archetype in
   the live merged registry (reporting per-archetype pass/fail); with a file argument, it
   **MUST** validate that file's definition without persisting it (a dry run ahead of `add`).

## Interface Contracts

### CLI Command Signatures

```text
docket roles list
docket roles show <name>
docket roles add <file.yaml>
docket roles validate [file.yaml]
```

### Wire format (a user archetype YAML file)

```yaml
name: producer
version: 1
scope: pod
modelClass: cheap
editRights: write
toolProfile: content-ops
description: coordinates content production across writer/critic
tokenBudget: 6000
deniedTools: []   # optional; e.g. ["write", "edit", "bash"] for a read-only role
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

  ## Session Startup
  Read ${requiredStartupFile}.

  ## Red Lines
  Stay within the `${project}` pod.
```

### Built-in archetypes (byte-identical to pre-W-6)

| Name | Scope | modelClass | policyRole | gateContract | editRights | tokenBudget | deniedTools |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lead` | pod | cheap | manager | none | none | 2000 | write, edit, bash |
| `implementer` | pod | strong | programmer | mechanical | write | 8000 | *(none)* |
| `reviewer` | pod | cheap | reviewer | verdict (APPROVE\|REQUEST-CHANGES) | read-only | 6000 | write, edit, bash |
| `tester` | pod | cheap | tester | verdict (PASS\|FAIL) | read-only | 4000 | write, edit |

### Starter library

| Name | Scope | modelClass | gateContract | editRights | tokenBudget | deniedTools |
| --- | --- | --- | --- | --- | --- | --- |
| `researcher` | pod | strong | none | write | 8000 | *(none)* |
| `analyst` | pod | strong | none | write | 8000 | *(none)* |
| `writer` | pod | cheap | none | write | 6000 | *(none)* |
| `critic` | pod | cheap | verdict (APPROVE\|REJECT) | read-only | 6000 | write, edit, bash |
| `operator` | pod | strong | mechanical | write | 8000 | *(none)* |
| `monitor` | pod | cheap | approval | read-only | 4000 | write, edit, bash |

### User overlay file

- Path: `~/.openclaw/docket-roles.json`
- Shape: `{"roles": {"<name>": {<archetype fields, camelCase>}}}`

### Return Codes

- `0`: success (listed/shown/added/validated cleanly)
- `1`: unknown subcommand, `show`/`add`/`validate` target not found or invalid, or a malformed
  archetype definition

## Examples

### Listing and inspecting archetypes

```bash
docket roles list
docket roles show reviewer
```

### Adding a custom archetype

```bash
docket roles add ./producer.yaml
# Added archetype 'producer' (scope=pod, modelClass=cheap).
```

### Validating before adding

```bash
docket roles validate ./producer.yaml
docket roles validate   # validates the whole live registry
```

## Validation

### Pre-conditions

- `~/.openclaw/` exists (created by `docket install`); `docket roles add`/`validate` create the
  overlay file's parent directory if needed

### Post-conditions

- `docket roles add` on a valid file leaves exactly one archetype added/overridden in
  `docket-roles.json`'s `roles:` map; no other key in that file is touched
- The four legacy archetypes' rendered SOUL.md/AGENTS.md remain byte-identical to the pre-W-6
  generators for any input, with no user overlay present

### Invariants

- `scope`, `modelClass`, `gateContract.kind`, and `editRights` are always one of their closed
  enum's values for every archetype the registry returns — `load_registry()` never returns an
  archetype that would fail its own `__post_init__` validation
- A malformed user-overlay entry never prevents the rest of the registry (built-ins, starter
  library, other user entries) from loading

## Changelog

### Version 1.4.0 (2026-08-02)

- **ROADMAP Phase 19, card P19-12 (per-role tool sets + identity composition).** Added
  `deniedTools` (open tuple of built-in tool names) to the archetype schema — see "Archetype
  schema" requirements 1/7, the revised requirement 5 (clarifying it is independent of
  `editRights`, not derived from it), and the new "Per-role tool sets" section. Added
  `core.archetypes.registry_for_role(base, role)`, the one function that turns this data into an
  actually-narrowed `ToolRegistry` via the public `ToolRegistry.without()` API — `core/agent_loop.py`
  calls it once per turn (see `agent-loop.spec.md`'s Version 1.1.0). Set `deniedTools` on every
  built-in/starter archetype matching its documented SOUL.md contract: `lead`/`reviewer`/`critic`/
  `monitor` = `write, edit, bash`; `tester` = `write, edit` (keeps `bash` to run the test suite);
  `implementer`/`researcher`/`analyst`/`writer`/`operator` = none (full access) — see the updated
  "Built-in archetypes"/"Starter library" tables. Unlike `tokenBudget` or `toolProfile`, this
  field is the first archetype field this spec claims is genuinely *enforced*, not merely
  descriptive — proven at the dispatch level, not by inspecting the data (see
  `agent-loop.spec.md`'s new Invariants). No change to rendered SOUL.md/AGENTS.md content
  (`deniedTools` doesn't participate in template rendering), no change to the CLI surface
  (`docket roles show` renders it as one more field in the existing YAML/JSON dump when
  non-empty), no golden impact.

### Version 1.3.0 (2026-07-30)

- **ROADMAP Phase 17, card C-1 (context compiler).** Added `tokenBudget` (positive integer) to
  the archetype schema — see "Archetype schema" requirement 1 and the new "Context-compiler token
  budget" section. Every built-in and starter-library archetype now declares one (`lead`: 2000,
  `implementer`: 8000, `reviewer`: 6000, `tester`: 4000, `researcher`/`analyst`/`operator`: 8000,
  `writer`/`critic`: 6000, `monitor`: 4000) — see the updated "Built-in archetypes"/"Starter
  library" tables. `from_wire` defaults a missing `tokenBudget` to `6000` rather than erroring, so
  a pre-C-1 `docket-roles.json` overlay entry keeps loading unchanged.
  `RoleArchetype.__post_init__` rejects a non-positive value the same way it already rejects a
  non-positive `version`. `core/context.py`'s `budget_for_role` is the one consumer today
  (`core/dispatch.py`'s `_hop_message`, via ROADMAP Phase 14 R-7's now-retired byte cap — see
  `pod-dispatch.spec.md`'s "Bounded hop prompts", rewritten by this same card). No change to the
  four legacy archetypes' rendered SOUL.md/AGENTS.md (`tokenBudget` doesn't participate in
  template rendering), no change to the CLI surface (`docket roles show` renders it as one more
  field in the existing YAML/JSON dump, not a new command or flag), no golden impact.

### Version 1.2.0 (2026-07-30)

- **ROADMAP Phase 16, card W-8 (generalized gates, shipped with W-2 per ROADMAP's sequencing
  rule).** `gateContract` is no longer descriptive-only data — `core.orchestrator.resolve_gate`
  consults it as a step's gate fallback whenever a pipeline step declares none of its own (see
  `pod-dispatch.spec.md`'s "Generalized gate execution"). No change to this spec's own schema,
  registry, or CLI surface; the "Legacy archetype fidelity" cross-check (requirement 3) is
  reworded now that `core/dispatch.py`'s private `_REVIEWER_VERDICT_RE`/`_TESTER_VERDICT_RE`
  constants it used to check against are deleted — the cross-check target is now
  `core/pipeline.py`'s `default_pipeline()` and the executor's own resolution, both verified to
  agree with this registry by test.

### Version 1.1.0 (2026-07-30)

- ROADMAP Phase 16 W-7 (pod blueprints) shipped: cross-referenced the new `pod-blueprints.spec.md`
  from the two places this spec previously described blueprints/preset rosters as future work
  ("tracked as ROADMAP Phase 16 W-7, not shipped"). No change to this spec's own schema, built-in
  archetypes, or CLI surface — blueprints compose archetype names by reference, they don't alter
  what an archetype is.

### Version 1.0.0 (2026-07-30)

- Initial specification (ROADMAP Phase 16 W-6): the archetype schema, the four built-in
  archetypes (byte-identical to the pre-W-6 hand-written generators), the six-role starter
  library, the `docket-roles.json` user-overlay pattern, the `modelClass` → role→model policy
  fallback, and `docket roles list/show/add/validate`.
