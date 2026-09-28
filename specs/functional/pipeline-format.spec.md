# Pipeline Format Specification

**Version**: 2.10.0
**Status**: Implemented — format, executor, variable resolution, and step-instruction
interpolation. **P30-3** adds a per-step `model` override (ADR 0012 §2 rule 6): a unit step may
declare `model: cheap|strong|<provider>/<id>`, resolved for that hop only — see "Steps"
Requirement 10 and "Short form" below; execution and resolution semantics live in
`pod-dispatch.spec.md` and `model-profiles.spec.md`. **P28-6** adds two more elements to control flow as bounded data (ADR 0010 §3):
a `when:` predicate that skips a step on a closed vocabulary, and a `run:` command step that
executes with no agent turn at all — see "Steps" Requirement 9 and the new "Conditional steps
and command steps" section below. **P27-5** removes this format's one remaining `role: lead` carve-out: a step's own
`instructions` now overrides the Lead's hop message too, the same as any other role — see "Steps"
Requirement 8 below and `role-archetypes.spec.md`'s "Hop instructions". The executor
(`core/orchestrator.py`, ROADMAP Phase 16 W-2) that runs a
`PipelineSpec` over the pod-dispatch state machine, and the `docket pipeline validate|plan|run`
CLI surface, now exist — see `pod-dispatch.spec.md` for execution semantics and
`cli-interface.spec.md` for the CLI contract. `core.pipeline.resolve_variables` (W-4) resolves a
caller-supplied `{name: value}` mapping (the serve webhook's JSON body, or `docket pipeline run
--var`) against a spec's declared `variables` before dispatch. **P26-7** closes this format's last
"not yet built" gap: a step's own `instructions` (see "Steps" below) may reference `${var}`-style
placeholders, interpolated from that resolved namespace by `core/dispatch.py`'s hop-message
builder; an unresolved reference anywhere refuses the whole run before any hop
(`core.pipeline.unresolved_step_variables`, called once by `dispatch_pod`). See
`role-archetypes.spec.md`'s "Hop instructions" for how a step's `instructions` interacts with a
target role's own declared or generated instruction. **P26-20** ships pre-authored
`pipeline.yaml` files as part of `templates/recipes/<name>/` — plain documents this format
already fully defines; see `role-archetypes.spec.md`'s "Shipped recipes" for the bundle
contract this spec does not itself own. **P28-3** adds a short form
(`core.pipeline.normalize_pipeline`): a step written as `<id>: <role-or-agent>` plus
`verify`/`verdict`/`approval`/`on` sugar, expanded into the exact canonical shape above before
validation — see "Short form" below. **P28-5** generalizes `on:` from a load-time refusal into a
real field: a step may now declare `on` (a mapping from an outcome label to a later or earlier
step, or to `fail`/`stop`) that the executor reads directly, and `until: verify` + `max` is
short-form sugar for a bounded self-retry — see "Outcome routing" below. The one bounded backward
edge the short form could already express keeps normalizing to the canonical `rework:` edge,
byte-identical to before; every other `on:` shape that used to be refused as "not available yet"
now loads. The canonical form itself, and everything this format's executor and CLI surface read
beyond the new field, is unchanged.
**Last Updated**: 2026-09-27

## Purpose

This specification defines **the docket-native pipeline format**: a single, Pydantic-modeled,
unknown-key-rejecting YAML dialect describing how a pod's roles are ordered, gated, and (later)
run in parallel. It is ROADMAP decision D-16's replacement for the Lobster YAML dialect — docket
used to lint Lobster but could not execute four of the constructs its own template emitted; this
format has no such gap because nothing in it is accepted that this spec doesn't also define. The
format is implemented by `core/pipeline.py`.

The **zero-migration contract** is this spec's central guarantee: a pod with no pipeline file
behaves exactly as `core/dispatch.py` behaves today (`PIPELINE_ORDER`: lead → implementer →
reviewer → tester, with today's exact gates). Nothing about installing this format changes an
existing pod's behavior until an operator opts in by writing a pipeline file.

## Scope

This specification covers:

- The `PipelineSpec` document shape: `name`, `description`, `variables`, `steps`
- Step targeting: a step names exactly one of a `role` or a specific `agent`, plus an optional
  `archetype` reference
- Per-step `retries` and `timeout` overrides
- Per-step `instructions` (P26-7) — an optional hop-instruction override, and its `${var}`
  interpolation from the run's resolved variable namespace
- The three gate kinds a step may declare: `mechanical` (a command), `verdict` (regex-matched
  marker output), and `approval`
- Bounded rework edges on a `verdict` gate (generalizing `core/dispatch.py`'s R-4 Reviewer →
  Implementer rework loop to an arbitrary earlier step and an arbitrary verdict vocabulary)
- `parallel` step groups — the data shape for concurrently-run child steps
- Pipeline-level `variables` (declared defaults / required placeholders) and their resolution
  (`resolve_variables`) and step-instruction interpolation (`interpolate_instructions`/
  `unresolved_step_variables`)
- Loading a pipeline from YAML text, including the **zero-migration** built-in pipeline returned
  when no file exists
- Structural validation (`validate_pipeline`) and its error contract

This specification does NOT cover:

- **Execution.** `core/pipeline.py` itself still never runs a step, spawns a process, or contacts
  a daemon — it only parses and validates a document into typed Python objects. Running a
  `PipelineSpec` over the pod-dispatch state machine (claiming, budget/approval gates, retries,
  crash resume), a bounded worker pool for `parallel` groups, per-step trace spans, and
  cancellation is `core/orchestrator.py` + `core/dispatch.py` (ROADMAP Phase 16 **W-2**, shipped)
  — see `pod-dispatch.spec.md`'s "Generalized gate execution", "Parallel step groups", and
  "Cancellation" sections.
- **The `docket pipeline`/`docket runs cancel` CLI surface itself** (argument shapes, exit codes,
  `--file`/`--resume`/`--timeout` flags) — see `cli-interface.spec.md`. This spec covers only the
  document format `docket pipeline validate`/the executor read. `docket pipeline plan` renders
  from the real executor's `core.orchestrator.resolve_plan`/`render_plan`, not a second
  pretty-printer.
- **The Lobster dialect itself**, its validator, or the mechanics of its retirement — see ROADMAP
  decision D-16 / Phase 16 card W-3, the durable retirement record (the former
  `workflow-integration.spec.md` was deleted per `specs/README.md`'s retired-spec convention).
- **Declarative role archetypes** (`archetype`'s registry: names, `modelClass`, `soulTemplate`,
  `gateContract`, …) — ROADMAP Phase 16 card **W-6** (shipped; see `role-archetypes.spec.md`).
  This spec's `archetype` field still validates only that a referenced name has archetype-slug
  *shape* — it never checks existence against the registry itself; that resolution (and the
  archetype-gateContract fallback when a step omits its own `gate`) is the executor's job
  (`core.orchestrator.resolve_gate`), documented in `pod-dispatch.spec.md`, not this format's.
- **Pod provisioning / blueprints** (which roles a pod actually has, `--count N` duplicate
  members, workspace kind) — see `workspace-structure.spec.md` and `pod-blueprints.spec.md`
  (ROADMAP Phase 16 card W-7, shipped). This spec only defines how a *step* may target a role or a specific member
  id; whether that role or id exists in a given pod is resolved at execution time — see
  `pod-dispatch.spec.md`'s `pod_full_roster`/`resolve_plan`.
- **Approval-gated dispatch's runtime semantics** (tokens, timeout-resolves-to-denied, the
  CLI/HTTP grant/deny surface) — see `security-gates.spec.md` and ROADMAP Phase 15 card G-1. This
  spec only defines the `approval` gate's on-disk shape; the pipeline-defined `approval` step is
  now a real, wired require_approval source — see `pod-dispatch.spec.md`.
- **Shipped recipe bundles** (`templates/recipes/<name>/`, P26-20) — a recipe's `pipeline.yaml` is
  an ordinary document this format validates the same way as any hand-authored file; the bundle
  contract (what else a recipe carries, how it names roles that need no YAML of their own, the
  "no new CLI surface" rule) is `role-archetypes.spec.md`'s "Shipped recipes".

## Requirements

### Document shape

1. A pipeline document **MUST** be a YAML mapping with `extra="forbid"` semantics at *every*
   nesting level (the document itself, every step, every gate, every rework edge, every
   variable): an unrecognized key anywhere **MUST** be a validation error, never silently
   ignored. This is the specific gap this format closes relative to the retired Lobster dialect,
   whose `validate` silently ignored `continueOnError`/`approval`/`outputs`/`notifications`
   (ROADMAP D-16).
2. A pipeline document **MUST** declare a non-empty `name` (`str`) and a non-empty `steps` list.
   `description` (`str`, default `""`) and `variables` (a mapping, default `{}`) are optional.
3. A pipeline document **MAY** declare a top-level `kind: pipeline`; `load_pipeline` strips it
   before validation, and any other `kind` value is a load error naming `pipeline` as the
   expected value. A document with no `kind` at all loads exactly as before — see "Short form"
   below for the sibling `kind`-bearing sugar this same load path expands.

### Variables

1. Each entry in `variables` **MUST** be a mapping with an optional `default` (any YAML scalar or
   structure, default `None`), an optional `description` (`str`, default `""`), and an optional
   `required` (`bool`, default `False`).
2. A variable **MUST NOT** declare both `required: true` and a non-null `default` — a required
   variable has no default by definition; a value **MUST** come from whatever invokes the
   pipeline (e.g. a webhook parameter — see Requirement 4).
3. A variable's key **MUST** be a valid identifier (`^[A-Za-z_][A-Za-z0-9_]*$`). Declaring a
   variable does not by itself cause any text substitution — that is a step's own choice, made by
   referencing `${name}` inside its `instructions` (see "Steps" Requirement 8 and "Step
   instruction interpolation" below); a variable this format's `variables` map never even
   declares may still be referenced this way, as long as the run's resolved namespace supplies it
   (Requirement 4's own "undeclared key passes through" rule).
4. **Variable resolution (ROADMAP Phase 16 W-4).** `core.pipeline.resolve_variables(spec,
   provided)` **MUST** produce the pipeline's final `{name: value}` namespace from a caller-supplied
   *provided* mapping (e.g. the serve webhook's JSON body — see `serve-read-api.spec.md`):
   - a name present in *provided* **MUST** win outright, whatever its value — an explicit `null`
     counts as "the caller supplied a value", not "absent";
   - a name declared in `variables` but absent from *provided* **MUST** fall back to that
     variable's `default` (`None` for one with no default);
   - a `required` variable absent from *provided* **MUST** raise `VariableError`; every missing
     required name **MUST** be named in one raised error, not just the first;
   - a key present in *provided* but not declared in `variables` **MUST** pass through unchanged —
     this function validates *presence* of required values, not a closed key set (unlike the
     document shape itself, which is `extra="forbid"` throughout).
   This function itself does not interpolate anywhere — it only produces the *namespace* that
   "Step instruction interpolation" below, and a caller inspecting what a dispatch ran with, read
   from. `docket pipeline run --var key=value` (repeatable; see `cli-interface.spec.md`) is the
   CLI's own *provided* source, the same role a webhook's JSON body plays.
5. **Step instruction interpolation (P26-7).** A step's own `instructions` (see "Steps"
   Requirement 8) may reference `${name}`-style placeholders — the exact `${name}` spelling only;
   a bare `$name` or a literal `$` (e.g. a dollar amount) is never treated as one. Before any hop
   of a dispatch runs, the executor **MUST** compute the run's resolved namespace (Requirement 4,
   above) and check every step's `instructions` (including `parallel` children) for a `${name}`
   reference *variables* does not resolve; if any exist, the whole run **MUST** be refused (no
   task claimed, no hop run) naming every unresolved name at once
   (`core.pipeline.unresolved_step_variables`). Once resolved, `core.pipeline.
   interpolate_instructions(text, variables)` substitutes each reference with the resolved
   value's string form before the hop-message builder ever sees the text — see
   `role-archetypes.spec.md`'s "Hop instructions" for how that interpolated text interacts with a
   target role's own instruction.

### Steps

1. Each entry in `steps` **MUST** have a non-empty, pipeline-unique `id` (`str`). Uniqueness
   **MUST** be checked across every step id in the document, including every child of every
   `parallel` group — a duplicate anywhere **MUST** be a validation error.
2. A **unit step** (one not using `parallel`) **MUST** target exactly one of `role` (`str`) or
   `agent` (`str`) — declaring both, or neither, **MUST** be a validation error.
3. `role` **MUST** be a lowercase slug (`^[a-z][a-z0-9_-]*$`) — the same shape `core/pod.py`'s
   pod roles and a future W-6 archetype name would both satisfy. This format does **not**
   restrict `role` to today's closed four-role set (`lead`/`implementer`/`reviewer`/`tester`);
   any slug-shaped value validates, since whether it names a role a given pod actually has is a
   dispatch-time concern, not this format's.
4. `agent` **MUST** be a non-empty string (a specific member id, e.g. `myapp-implementer-2`);
   this format does not check that the id exists or belongs to any particular pod.
5. A step **MAY** declare `archetype` (`str`) — a plain reference to a ROADMAP Phase 16 W-6 role
   archetype name. It **MUST** be a lowercase slug (same shape as `role`); its *existence* against
   any archetype registry is explicitly **NOT** checked by this format (see Scope).
6. A step **MAY** declare `retries` (`int`, `>= 0`) and/or `timeout` (`int`, `> 0`, seconds).
   Omitting either (`None`, the default) **MUST** mean "defer to whatever role-level or pod-level
   default the executor applies" — the same "explicit override, else a fallback" convention
   `core/dispatch.py` already uses for its own `turnTimeoutS`/`verifyTimeoutS`/per-role retry
   budget (see `pod-dispatch.spec.md`).
7. A step **MAY** declare a `gate` (see "Gates" below) or omit one entirely (no gate — the step
   always advances once its turn completes, matching today's Lead hop).
8. A unit step **MAY** declare `instructions` (`str`) — its own hop instruction, overriding
   whatever the target role would otherwise carry (a built-in role's hardcoded text, or a custom
   role's own `hopInstruction`/generated fallback; see `role-archetypes.spec.md`'s "Hop
   instructions"). Omitting it (`None`, the default) means "defer to the role" — not "no
   instruction at all". It **MAY** reference `${name}`-style variables, interpolated per
   "Variables" Requirement 5. A step whose target is `role: lead` **MUST** have its `instructions`
   applied like any other role (P27-5): it replaces the Lead's own instruction text (the built-in
   hardcoded line, or an overlaid `lead` archetype's `hopInstruction`) instead of being ignored.
9. A unit step **MAY** target `run` (`str`, a shell command) instead of `role`/`agent` —
   declaring `run` alongside either **MUST** be a validation error, the same "exactly one
   target" rule Requirement 2 states for `role`/`agent`. A `run` step (a "command step") **MUST
   NOT** also declare `gate`, `instructions`, `retries`, `archetype`, or `model` — each is a
   validation error naming the field. It **MAY** still declare `timeout` and `when` (see
   "Conditional steps and command steps" below). Its exit code is its own outcome; this format
   does not model a separate `gate` for it (see `pod-dispatch.spec.md` for execution).
10. A unit step **MAY** declare `model` (`str`) — one of the literal rank words `cheap`/`strong`,
    or a `<provider>/<id>` model literal shaped like any other model id this codebase accepts
    (a non-empty segment either side of the first `/`). It overrides whatever model this hop's
    target would otherwise run on, for that hop only (see `pod-dispatch.spec.md`'s "Per-hop
    execution" and `model-profiles.spec.md`'s "Model intent per agent" for resolution and the
    never-persisted guarantee). This format validates only the literal's *shape* — whether a
    `<provider>/<id>` literal's provider actually exists in the provider catalog is a
    plan/dispatch-time concern, not this format's (the same posture Requirement 5 takes for
    `archetype`). Omitting it (`None`, the default) means "defer to the role/pin/policy resolution
    that already applies today". A parallel group **MUST NOT** declare `model` at the group level
    (only its children may) — same rule as `instructions`.

### Gates

1. A `gate` **MUST** be one of exactly three kinds, discriminated by its own `type` field:
   `mechanical`, `verdict`, or `approval`. An unrecognized `type` **MUST** be a validation error.
2. **`mechanical`** — `command` (`str | None`, default `None`) and `timeout` (`int | None`, `> 0`
   if given). A non-zero exit from `command` fails the step. `command: None` **MUST** be
   interpreted as "defer to the target agent's own configured check" (today's Implementer
   `verifyCmd` meta field — see `docket-meta.spec.md`) rather than "no check" — this is what lets
   the built-in default pipeline (see "Zero migration" below) express today's exact behavior
   without inventing a literal command that doesn't exist in the format.
3. **`verdict`** — `pattern` (`str`, a non-empty, compilable regular expression whose first
   capturing group is the verdict marker), `passValues` (`list[str]`, non-empty), `caseSensitive`
   (`bool`, default `false`), and an optional `rework` edge (see "Rework edges" below). A matched
   marker (normalized per `caseSensitive`) present in `passValues` **MUST** allow the pipeline to
   advance; a marker matched by `rework`'s `when` list **MUST** trigger a bounded rework cycle
   (see below); any other outcome — including no match at all (unparseable output) — **MUST**
   fail the step. `passValues` and `rework.when` **MUST NOT** share any value (after the same
   case-normalization) — a marker cannot mean both "pass" and "rework" at once. The executor
   **MUST** apply the pattern independently at the start of every non-blank output line, collect
   and normalize every first capture, and accept exactly one distinct normalized value. Repeated
   matches of that same value collapse to one. Zero matches or multiple distinct values are
   unparseable. A marker mentioned later in prose is not a match, and scanning never falls back to
   substring search.
4. **`approval`** — an optional `message` (`str`, default `""`) shown to whoever grants the
   approval. This format defines only the gate's shape; its wiring to docket's approval store
   (tokens, grant/deny, timeout-resolves-to-denied) shipped with Phase 15 G-1 / W-2 and is
   specified in `pod-dispatch.spec.md` and `security-gates.spec.md`, not here.

### Rework edges

1. A `rework` edge on a `verdict` gate **MUST** have a `to` (`str`, a non-empty step id), a `when`
   (`list[str]`, non-empty — the verdict marker values that trigger the edge), and a `maxCycles`
   (`int`, `>= 0`, default `1`).
2. `maxCycles: 0` **MUST** be a valid, meaningful value: it declares the edge but disables it (the
   gate behaves as a hard block on every `when` value, matching `core/dispatch.py`'s Tester gate,
   which has no rework loop at all). A gate that never rejects for rework at all simply omits
   `rework` entirely — both are valid, distinct ways to express "no rework".
3. This field is named `when`, not `on`, deliberately: YAML 1.1's implicit-boolean resolver (the
   one PyYAML's `safe_load` implements) parses a bare `on:` key as the boolean `True` unless
   quoted — the same "Norway problem" that affects GitHub Actions' top-level `on:` key. Naming the
   field `when` avoids the trap entirely rather than requiring every pipeline author to remember
   to quote a key.
4. `to` **MUST** name an existing **top-level** step id (not one nested inside a `parallel`
   group) that occurs **strictly earlier** in the `steps` list than the step declaring the
   `rework` edge. Referencing a non-existent id, a step at or after the declaring step's own
   position, or a step nested inside a `parallel` group **MUST** be a validation error.
5. A step nested inside a `parallel` group **MUST NOT** declare a `rework` edge on its own gate —
   join semantics for a rework inside a fan-out are an executor concern this format does not
   define; the validation error names the offending child step.
6. `rework` **MUST** remain the canonical spelling of the one bounded backward verdict edge to an
   earlier step; the more general `on:` field (see "Outcome routing" below) generalizes it to a
   later step, a `fail`/`stop` terminal, or more than one outcome label, without replacing it.

### Parallel groups

1. A step **MAY** be a **parallel group** instead of a unit step: it sets `parallel` to a
   non-empty list of unit steps that the executor runs concurrently on a bounded worker pool
   (`pod-dispatch.spec.md`'s "Parallel step groups") — e.g. one per `--count N` duplicate role
   member of a pod.
2. A parallel-group step **MUST NOT** also declare `role`, `agent`, `gate`, `retries`, `timeout`,
   or `instructions` at the group level — only its children carry those; declaring any of them on
   the group itself **MUST** be a validation error.
3. Nesting **MUST** be limited to exactly one level: a child of a `parallel` group **MUST NOT**
   itself declare `parallel`. A nested `parallel` **MUST** be a validation error naming the
   offending child.
4. Each child of a `parallel` group **MUST** independently satisfy every unit-step requirement
   above (a unique id, exactly one of `role`/`agent`, valid `archetype`/`retries`/`timeout`/
   `gate` shape) except the rework-edge restriction in "Rework edges" item 5.

### Zero migration

1. Loading a pipeline with no supplied text (`text=None` — the caller determined no pipeline file
   exists for this pod) **MUST** return a built-in `PipelineSpec` equivalent to `core/dispatch.py`
   's hardcoded pipeline: Lead (no gate) → Implementer (`mechanical` gate, `command: None`,
   deferring to the target's own `verifyCmd`) → Reviewer (`verdict` gate, pattern
   `^\s*(APPROVE|REQUEST-CHANGES)\b`, `passValues: [approve]`, a `rework` edge to `implementer`
   on `request-changes` with `maxCycles: 1`) → Tester (`verdict` gate, pattern
   `^\s*(PASS|FAIL)\b`, `passValues: [pass]`, no rework).
2. This built-in pipeline **MUST** be exactly the pipeline `core/dispatch.py`'s own
   `PIPELINE_ORDER` constant and Reviewer/Tester verdict regexes describe — a pod with no
   pipeline file today behaves identically whether or not this format exists at all. (This
   equivalence is drift-guarded by test, not merely documented — see "Validation" below.)
3. Loading a pipeline with an explicitly **empty** string (an existing-but-empty file) **MUST NOT**
   be treated as the zero-migration case — it **MUST** be a validation error (an empty document),
   distinct from "no file at all".
4. A pod whose actual roster doesn't include every role this built-in pipeline names (e.g. a lean
   pod with no Reviewer/Tester) is unaffected by this format at all — which roles a pod has is a
   dispatch-time/provisioning concern (`pod-dispatch.spec.md`'s `pod_pipeline`, which already
   skips absent roles); this format's built-in pipeline just names the full four-role sequence
   that constant already encodes.

### Loading and validation

1. `load_pipeline(text)` **MUST** return a result carrying exactly one of: a validated
   `PipelineSpec` (`errors == []`), or a non-empty list of human-readable error strings
   (`spec is None`). It **MUST** also report its `source` — `"builtin"` for the zero-migration
   case, `"file"` otherwise.
2. A YAML parse error, an empty document, or a document that isn't a mapping **MUST** each produce
   exactly one descriptive error string and no `spec`.
3. A schema violation (unknown key, missing required field, wrong type, an XOR violation, a
   rework-bound violation, a duplicate id, …) **MUST** produce one error string per violation,
   each naming the offending field's dotted location.
4. `validate_pipeline(text)` **MUST** be a thin wrapper equivalent to `load_pipeline(text).errors`
   — structural validation only, kept as a separate entry point for callers that only want the
   error list.
5. If PyYAML is unavailable, `load_pipeline`/`validate_pipeline` **MUST** report an actionable
   error (naming `pip install pyyaml`) rather than raising an unguarded `ImportError` — the same
   defensive-import convention `cli/_agents.py` already follows, even though PyYAML is a declared
   runtime dependency (`pyproject.toml`).

### Short form

1. `core.pipeline.normalize_pipeline(doc: dict) -> dict` **MUST** be a pure function: given a
   parsed YAML document, it returns the canonical mapping this format's Requirements above
   already define, without touching the filesystem or mutating its argument. `load_pipeline`
   **MUST** call it on every document (after stripping a `kind: pipeline` key, if present) before
   `PipelineSpec` validation; a document already written in canonical form **MUST** pass through
   unchanged. The canonical form remains fully valid on its own and is what the executor, `plan`,
   and every other reader see — nothing downstream of `load_pipeline` is aware the short form
   exists.
2. A `steps` entry **MUST** be read as short form when it is a mapping with exactly one key whose
   value is a string and is not one of the sugar keys below (a one-key mapping `{<id>: <target>}`,
   or that same key alongside sugar keys); that key becomes the step's `id` and its string value
   the step's target. A mapping that already carries an `id` key, or that does not resolve to
   exactly one such key, **MUST** be left unchanged (read as canonical form, including a `id`-less
   `parallel` group, which this version of the short form does not cover).
3. The target string **MUST** become `role:` when it is one of `lead`/`implementer`/`reviewer`/
   `tester`, or when it is not shaped like a pod member id; it **MUST** become `agent:` when it is
   shaped like one — a `pod.parse_member_id`-style id (`<prefix>-<role>` or
   `<prefix>-<role>-<index>` where `<role>` is one of the four base roles above), recognized by
   shape alone, the same way this format's `archetype` field validates a slug's *shape* without
   checking it against any registry (see "Scope"). `security-vetter` is therefore a `role:` (its
   last hyphen-separated segment, `vetter`, is not a base role); `myshop-implementer` and
   `myshop-implementer-2` are `agent:`.
4. The recognized sugar keys, each optional, **MUST** be mapped as follows:
   - `verify: true` → `gate: {type: mechanical}`; `verify: "<command>"` → `gate: {type:
     mechanical, command: "<command>"}`.
   - `verdict: [<marker>, ...]` (at least one marker) → `gate: {type: verdict, pattern:
     '^\s*(<marker>|...)\b', passValues: [<first marker, lowercased>]}`, each marker escaped for
     regex safety; the first marker is the passing value, the rest are outcomes a step's `on:`
     (below) or an unparsed non-match may still fail on, exactly as the canonical `verdict` gate
     already does.
   - `approval: "<message>"` → `gate: {type: approval, message: "<message>"}`.
   - `instructions`, `timeout`, `retries`, `model` carry straight through to the same-named
     canonical field.
   - `on: {<label>: {goto: <earlier step id>, max: <n>}}` **MUST**, when the step also carries a
     `verdict` sugar key **and** this is the single bounded backward edge described above, become
     that gate's `rework: {to: <goto>, when: [<label, lowercased>], maxCycles: <n>}`. Because
     PyYAML's default resolver reads an unquoted `on:` key as the boolean `True` (the same
     implicit-boolean pitfall `rework`'s own `when` field name was chosen to avoid — see "Rework
     edges" above), this format **MUST** accept the sugar key spelled either as the literal string
     `"on"` or as the boolean `True` a bare `on:` actually parses to — including on a step that is
     already written in canonical (`id`-bearing) form, since that same key survives YAML parsing
     unchanged either way. Every other `on:` shape **MUST** instead become the step's own
     canonical `on` field verbatim (see "Outcome routing" below), never a load error.
   - `until: "verify"` with a `max` sugar key **MUST**, on a step that also carries (or resolves
     to) a `mechanical` gate, become that step's `on: {fail: {goto: <this step's own id>, max:
     <n>}}` — a bounded self-retry. `until`/`max` are short-form-only: the canonical form never
     carries `until`, and `max` alone (without `until`) or `until` on a non-mechanical step **MUST**
     each be a load error naming the step. `until`/`max` **MUST NOT** be combined with an explicit
     `on:` sugar key on the same step.
   - A step carrying no sugar key beyond `instructions`/`timeout`/`retries` **MUST** get no `gate`
     at all — the target role's own contract applies, exactly as an `id`/`role` step with no
     `gate` does today.

### Outcome routing

1. A step **MAY** declare `on` (`dict[str, Route] | None`), a canonical field alongside `gate`: a
   mapping from an outcome label — a verdict gate's matched marker, or `"pass"`/`"fail"` for a
   mechanical gate, each compared case-insensitively — to a `Route`. A `Route` is either a mapping
   `{goto: <step id>, max: <int >= 1>}` (`max` **MUST** be present when `goto` names a step at or
   before this one) or one of the literal strings `"fail"`, `"stop"`, or a bare step id (a forward
   target equivalent to `{goto: <that id>}` with no bound).
2. At execution time (`pod-dispatch.spec.md`'s "Generalized gate execution"), a gate outcome named
   in the step's own `on` map **MUST** be routed — to `fail` (the task fails), `stop` (the task
   ends `done`), or the named step (the pipeline continues there, a backward or self target
   counted against its own `max`) — instead of that outcome's ordinary handling. This is a real
   override: an outcome that would otherwise plainly advance, rework, or fail can be redirected;
   an outcome the map does not name behaves exactly as it always has, including a built-in role's
   legacy trace event names.
3. `PipelineSpec` **MUST** validate every `on` entry: a `goto`/bare-step-id target **MUST** name an
   existing step id in the document (forward or backward now both valid) or be `fail`/`stop`; a
   backward or self target without `max` **MUST** be a validation error naming the step; and a
   step that no execution path reaches — walking from the first step through its default
   successor and every `on` target, never continuing past a `fail`/`stop` terminal — **MUST** be a
   validation error naming the unreachable step. `plan`/`validate` render every step's routes
   alongside its gate.
4. The one recognized single-bounded-backward-edge shorthand (see "Short form" above) **MUST**
   keep normalizing to the canonical `rework:` edge, never to `on`, so every existing rework-based
   document and the three shipped recipes stay byte-identical.

### Conditional steps and command steps

1. Any step (unit or command) **MAY** declare `when` — a closed, code-implemented predicate
   vocabulary, never a general expression language: `changed` (`str`, a glob matched against the
   working tree's changed paths), `var` (`str`, a pipeline variable name) paired with `is` (`str`,
   its expected resolved string form), and `memberPresent` (`str`, a pod role). `var` and `is`
   **MUST** be set together — one without the other is a validation error. At least one predicate
   **MUST** be set; declaring `when` with none is a validation error. Declaring more than one
   predicate **MUST** mean every one is ANDed together — this format defines no `anyOf`/`not` for
   `when`, the same closed-vocabulary posture `security-gates.spec.md`'s policy predicates take.
   A false predicate skips the step (see `pod-dispatch.spec.md` for the skip/trace mechanics);
   this format only defines the shape.
2. `run` (Steps Requirement 9) is this format's command step: a plain shell command string, run
   with no agent turn at all — the language-agnostic escape hatch ADR 0010 §3 describes. Its
   `timeout` (if set) bounds the command the same way a `mechanical` gate's own `timeout` bounds
   a verify command; its exit code and (when the command step also carries an `on:` outcome map —
   a later format version, not this one) its last stdout line are its outcome, entirely an
   execution concern this format does not itself model as a `gate`.
3. `docket pipeline validate`/`plan` **MUST** treat a `when`/`run` shape violation exactly like
   any other schema violation (one error string naming the offending field's dotted location);
   `plan`'s rendering of a `run` step and a `when`-bearing step is specified in `pod-dispatch.spec.md`
   (the executor) since this format itself defines no renderer.

### Operator input steps (P34-7: format only, no execution yet)

1. `input` is this format's operator-input step: a pipeline pause that asks the operator a
   question, exclusive of `role`/`agent`/`run`/`parallel` — one and only one of these five
   **MUST** be set on any unit step. An `input` step names a prior step as its `from:` source and
   MAY declare a `message` (the operator question) and `expires_hours` (how long an answer is
   valid). Its `on:` outcome routing, when present, **MUST** use only keys `answered` or
   `declined` (case-insensitive) — any other key is a validation error. An `input` step
   **MUST NOT** declare `gate`, `retries`, `timeout`, `instructions`, or `model`.
2. `input.from_` (aliased as `from:` in YAML) **MUST** be the id of a step that precedes this
   one in the pipeline order — a forward or self reference is a validation error naming the
   step id and the bad source.
3. `plan` renders an `input` step as `asks the operator (from <source-step-id>)`, the same
   rendered-once, never-executed posture a `run` step already takes (output shows what *would*
   run if execution were available, never *that it ran*).
4. Execution of an `input` step is **NOT YET IMPLEMENTED** (owned by P34-10). The executor
   raises with the message `"step <id>: an 'input' step cannot run yet — only 'plan' renders it
   (P34-10 implements execution)"` if an `input` step is ever reached during dispatch.

## Interface Contracts

This spec defines a Python data model and pure functions in `core/pipeline.py`. The CLI surface
that reads it (`docket pipeline validate|plan|run`) is documented in `cli-interface.spec.md`; the
executor that runs it (`core/orchestrator.py`, `core/dispatch.py`) is documented in
`pod-dispatch.spec.md` (see "Does NOT cover"). A third caller validates a file for **storage**
rather than one-off execution: `docket pod <project> config set pipeline <file>` calls
`load_pipeline` to validate a would-be **bound pipeline** before persisting a copy of it, per
`pod-dispatch.spec.md`'s "Pipeline order and participation" requirement 6 and "Pod dispatch
settings". This format itself is unchanged by that caller — no new field, no storage concept
lives here.

```python
from docket.core.pipeline import load_pipeline, validate_pipeline, default_pipeline

result = load_pipeline(text_or_none)
result.ok        # bool: spec is not None and errors == []
result.spec       # PipelineSpec | None
result.errors     # list[str]
result.source     # "file" | "builtin"

errors = validate_pipeline(text)   # == load_pipeline(text).errors

builtin = default_pipeline()       # the zero-migration PipelineSpec, unconditionally
```

Short form (Requirement, "Short form"):

```python
from docket.core.pipeline import normalize_pipeline

normalize_pipeline(doc)   # dict -> dict: short-form sugar expanded into the canonical
                           # mapping above; a canonical document passes through unchanged.
                           # load_pipeline calls this before PipelineSpec.model_validate;
                           # callers of load_pipeline never need to call it themselves.
```

Variable resolution (Requirement 4, ROADMAP Phase 16 W-4):

```python
from docket.core.pipeline import resolve_variables, VariableError

values = resolve_variables(spec, provided)   # provided: dict[str, Any] | None
# -> dict[str, Any]: every declared variable resolved (provided value, else default),
#    plus any undeclared key from `provided` passed through unchanged.
# Raises VariableError naming every missing `required` variable at once.
```

Step instruction interpolation (Requirement 5, P26-7):

```python
from docket.core.pipeline import (
    interpolate_instructions,
    step_instructions_by_id,
    unresolved_step_variables,
)

step_instructions_by_id(spec)              # -> dict[str, str]: step id -> its own declared
                                            #    `instructions`, not yet interpolated (a step
                                            #    with none is simply absent)
unresolved_step_variables(spec, values)    # -> list[str]: every `${name}` no step's
                                            #    `instructions` can resolve from `values`,
                                            #    sorted; [] means the run may proceed
interpolate_instructions(text, values)     # -> str: `${name}` substituted from `values`
                                            #    (stringified); an unresolved reference is
                                            #    left literal -- callers check with
                                            #    unresolved_step_variables first
```

## Examples

### A minimal pipeline (lean pod: no rework, no parallel)

```yaml
name: ship-feature
description: Build and verify a change.

steps:
  - id: plan
    role: lead

  - id: build
    role: implementer
    gate:
      type: mechanical
      command: "pytest -q"
```

### The full shape: variables, a bounded rework edge, and a parallel fan-out

```yaml
name: release
description: Ship a change through the pod, fanning work out across two implementers.

variables:
  TARGET:
    default: main
    description: branch to ship
  REASON:
    required: true

steps:
  - id: plan
    role: lead

  - id: fanout
    parallel:
      - id: impl-a
        agent: myapp-implementer
        instructions: "Focus on ${TARGET}."
      - id: impl-b
        agent: myapp-implementer-2

  - id: review
    role: reviewer
    gate:
      type: verdict
      pattern: "^(APPROVE|REQUEST-CHANGES)\\b"
      passValues: [approve]
      rework:
        to: fanout
        when: [request-changes]
        maxCycles: 2

  - id: ship
    role: implementer
    gate:
      type: approval
      message: "Ready to deploy?"
```

### An unknown key is rejected, not ignored

```yaml
name: broken
steps:
  - id: build
    role: implementer
    verifyCommand: "pytest -q"   # typo: not a real field
```

```text
>>> load_pipeline(text).errors
["steps.0.verifyCommand: Extra inputs are not permitted"]
```

## Validation

### Pre-conditions

- The caller has already decided whether a pipeline file exists for the pod in question — this
  module performs no filesystem I/O itself (`core/` never does; see `edges/store.py`'s role as
  the sole JSON I/O chokepoint). Passing `None` is how a caller expresses "no file".

### Post-conditions

- A successfully loaded `PipelineSpec` satisfies every requirement in this document — there is no
  "valid but not fully checked" state, unlike the retired Lobster dialect's `validate` (ROADMAP
  D-16), which silently ignored several keys its own template emitted.
- `default_pipeline()` itself satisfies every validator `PipelineSpec` enforces for a
  hand-authored file — it is not exempt from its own rules (test-pinned).

### Invariants

- Every level of the document (`PipelineSpec`, `Step`, `MechanicalGate`, `VerdictGate`,
  `ApprovalGate`, `ReworkEdge`, `Variable`) rejects unknown keys.
- `default_pipeline()`'s role order **MUST** equal `core/dispatch.py`'s `PIPELINE_ORDER` tuple
  — checked directly, by test (`tests/unit/core/test_pipeline__spec.py::TestZeroMigration`), not a
  hand-copied literal that could silently drift. Its Reviewer/Tester `pattern`/`passValues` no
  longer have a dispatch-private regex constant to cross-check against (W-8 deleted
  `core/dispatch.py`'s own hardcoded copy once gate execution went generic) — the drift guard is
  now that `core.orchestrator.resolve_gate`'s archetype-gateContract fallback (a bare `role:
  reviewer`/`role: tester` step with no `gate` of its own) produces the byte-identical `pattern`
  and case-insensitively equal `passValues` (`APPROVE`/`PASS` from the archetype, `approve`/`pass`
  in `default_pipeline()`; both gates are `caseSensitive: false`) that `default_pipeline()`'s
  explicit gates declare, checked by the same test class and by
  `tests/integration/test_archetypes.py`.
- This format module itself (`core/pipeline.py`) still contains no executor, CLI command, or
  dry-run renderer — those now exist, but in `core/orchestrator.py` and `cli/_pipeline.py`
  respectively (see "Does NOT cover").

## Changelog

### Version 2.10.0 (2026-09-27)

- **P30-3: a pipeline step names its model (ADR 0012 §2 rule 6).** `Step` gains `model`
  (`cheap`/`strong`/`<provider>/<id>`, shape-validated only — see Steps Requirement 10), forbidden
  on a `parallel` group's own entry and on a `run` command step, carried through the short form
  like `timeout`/`retries`/`instructions`. Resolution (rank word → live rank anchor, per-hop,
  never persisted), the unresolvable-provider refusal, and `plan`'s `model=<x>` rendering are
  `pod-dispatch.spec.md`'s and `model-profiles.spec.md`'s concern; no existing document changes
  meaning, since a step with no `model` behaves exactly as before.

### Version 2.9.0 (2026-09-26)

- **P28-6: conditional (`when`) and command (`run`) steps.** New "Conditional steps and command
  steps" requirements subsection (ADR 0010 §3) and Steps Requirement 9. `Step` gains `when` (a
  new `When` model: `changed`/`var`+`is`/`memberPresent`, closed vocabulary, every set predicate
  ANDed, at least one required) and `run` (a command step, exclusive of `role`/`agent`, carrying
  no `gate`/`instructions`/`retries`/`archetype` of its own). Short form gains a nested shape:
  `- lint: {run: "ruff check ."}` (a one-key mapping whose value is itself a mapping carrying
  `run`) expands to `{id: lint, run: ..., timeout?, when?}` in `_normalize_short_step`; a string
  target (`- lint: "ruff check ."`) is still a role/agent, never a command step. No change to any
  existing document — every prior valid pipeline (including the three shipped recipes) still
  loads and renders byte-identically. Execution (skip mechanics, command-step outcome, the
  approval/refuse posture on a non-allowlisted command) is `pod-dispatch.spec.md`'s
  "Conditional steps and command steps".
### Version 2.8.0 (2026-09-26)

- **P28-5: outcome routing generalizes `on:` beyond one bounded rework edge.** New "Outcome
  routing" requirements subsection: a step may now declare a canonical `on` field mapping an
  outcome label (a verdict marker, or `pass`/`fail` for a mechanical gate) to `fail`, `stop`, or a
  forward or backward step id (a backward or self target requires `max`); the executor
  (`pod-dispatch.spec.md` v6.19.0) routes a named outcome instead of its ordinary handling.
  `until: "verify"` + `max` short-form sugar rewrites to a bounded self-retry (`on: {fail: {goto:
  <self>, max}}`); both are short-form-only, so the canonical form never carries `until`.
  `PipelineSpec` gains two new validators: every `on` target must resolve, and a backward/self
  target without `max` or a step no execution path reaches is a load error naming it. "Rework
  edges" gains one sentence: `rework` stays the canonical spelling of the one bounded backward
  verdict edge, which `on:` generalizes rather than replaces — the short form's own single
  bounded-backward-edge sugar keeps normalizing to `rework:`, never to `on`, so every existing
  rework-based document and the three shipped recipes stay byte-identical. Every other `on:` shape
  that "Short form" Requirement 5 used to refuse as "not available yet" now loads.

### Version 2.7.0 (2026-09-26)

- **P28-3: a short form for steps.** New "Short form" requirements subsection and one new
  Document shape requirement (`kind: pipeline`, optional, stripped before validation). Adds
  `core.pipeline.normalize_pipeline(doc: dict) -> dict`, called by `load_pipeline` before
  `PipelineSpec.model_validate`: a step written as `<id>: <role-or-agent>` plus `verify`/
  `verdict`/`approval`/`instructions`/`timeout`/`retries`/`on` sugar expands into the exact
  canonical mapping this format already validated. No schema change — the canonical
  `PipelineSpec`/`Step`/`Gate`/`ReworkEdge` models are unchanged, and every existing document
  keeps loading unmodified. `on:`'s only implemented shape is the single bounded backward edge
  (`{goto, max}` on a verdict step); every other shape (`fail`, `stop`, a forward edge, more than
  one label) is a load error naming the step, and a backward `goto` missing `max` gets its own
  message saying so, since outcome-map execution and reachability checks are a later format
  version's job, not this card's. The three shipped recipes
  (`templates/recipes/{ops-approval,research-review,secure-build}/pipeline.yaml`) are rewritten
  in short form; each still resolves to the byte-identical `PipelineSpec` (and therefore the same
  `docket pipeline plan` rendering) it did before this version.

### Version 2.6.0 (2026-09-26)

- **P27-5: step `instructions` now reach `role: lead`.** Steps Requirement 8 rewritten: a step
  targeting `role: lead` no longer has its `instructions` silently ignored — it overrides the
  Lead's own instruction text exactly like any other role. No schema change (the field already
  existed); the Lead-specific exemption was in behavior only, closed on the `core/dispatch.py`
  side by the same card — see `role-archetypes.spec.md` v1.14.0 and `pod-dispatch.spec.md`
  v6.17.0.

### Version 2.5.0 (2026-09-26)

- **P26-20: shipped recipes reference this format's own validators.** No schema change. Added
  the "Does NOT cover" note pointing at `role-archetypes.spec.md`'s "Shipped recipes" for
  `templates/recipes/<name>/`'s `pipeline.yaml` files, and pinned by test that each one passes
  `validate_pipeline` and resolves against a fixture pod with no skipped step.

### Version 2.4.0 (2026-09-26)

- **P26-7: step `instructions` and `${var}` interpolation.** Added the optional per-step
  `instructions` field (Steps Requirement 8) and closed this format's last "not yet built" gap
  from v2.0.0/W-4: a step's `instructions` may reference `${name}`-style placeholders, resolved
  from `resolve_variables`'s own output and substituted by the new `interpolate_instructions`
  before the hop-message builder sees the text. The new `unresolved_step_variables` is the
  preflight the dispatch executor runs once, up front — an unresolved reference anywhere refuses
  the whole run before any hop, no task claimed. `docket pipeline run` gained repeatable `--var
  key=value` as this CLI surface's own *provided* source (`cli-interface.spec.md`). See
  `role-archetypes.spec.md` v1.8.0's companion `hopInstruction`/`resolve_hop_instruction` for how
  a step's `instructions` interacts with the target role's own instruction.

### Version 2.3.0 (2026-09-26)

- **P26-6.** Documents a third `load_pipeline` caller: `docket pod <project> config set
  pipeline <file>` (see pod-dispatch.spec.md), which validates a file before storing a bound
  copy of it rather than running it once. No change to the format, the model, or
  `load_pipeline`/`validate_pipeline` themselves — this is a doc-only cross-reference.

### Version 2.2.1 (2026-09-19)

- Doc-truth pass, no behavior change. Removed three stale "Does NOT cover" bullets left over from
  1.0.x that contradicted the current ones: "no executor exists yet", "no `docket pipeline` CLI",
  and "no plan renderer". Also removed a duplicate Lobster bullet claiming `docket workflow`
  still serves Lobster (W-3 retired it). Marked W-7 blueprints as shipped. The approval gate's
  wiring is now described as shipped, and parallel groups as run by the executor's bounded pool.
  The zero-migration drift-guard invariant now says `passValues` agree case-insensitively, as
  the test asserts, rather than byte-for-byte.

### Version 2.2.0 (2026-08-30)

- **Wave 25 card W25-C11.** Verdict parsing now treats the configured pattern as a line-anchored
  marker contract over the complete output rather than a first-non-blank-line contract. One
  distinct normalized marker is accepted wherever its line appears; repeated identical markers
  collapse, while zero or conflicting distinct markers fail closed. The format and persisted
  pipeline shape are unchanged.

### Version 2.1.0 (2026-07-30)

- **ROADMAP Phase 16, card W-4 (durable scheduling + event triggers).** Added
  `core.pipeline.resolve_variables`/`VariableError` (Requirement 4): the variable resolution this
  format's `Variable`/`PipelineSpec` always declared but never implemented. `docket serve`'s
  `POST /dispatch/<project>` webhook (see `serve-read-api.spec.md`) is the first caller — its JSON
  body is resolved against the pod's effective pipeline's declared `variables` before a run record
  is even created, and a missing `required` variable is rejected with 400 before anything is
  dispatched. This is additive (a new function, no schema change to `PipelineSpec` itself) and
  does not implement text interpolation (Requirement 3 is unchanged and still open).

### Version 2.0.0 (2026-07-30)

- **ROADMAP Phase 16, card W-2 (executor) / W-8 (generalized gates), shipped together per
  ROADMAP's sequencing rule** ("W-6/7/8 land with the executor, not after"). This format itself is
  unchanged — no new fields, no schema migration — but its "Does NOT cover" list shrinks
  substantially now that the things it named as not-yet-built actually exist:
  - `core/orchestrator.py` resolves a `PipelineSpec` (this format) against a pod's live roster
    into a deterministic `ExecutionPlan`, and runs it over the R-1 state machine
    (`core/dispatch.py`) — claiming, budget/require_approval gates, retries, and crash resume all
    apply to a custom spec exactly as they always have to the built-in one. See
    `pod-dispatch.spec.md`'s new "Generalized gate execution", "Parallel step groups", and
    "Cancellation" sections for the executor's behavioral contract.
  - `docket pipeline validate|plan|run` (see `cli-interface.spec.md`) is the first CLI surface to
    read this format. `plan` renders directly from `core.orchestrator.resolve_plan`/`render_plan`
    — the same function the real executor calls — never a second, drift-prone pretty-printer.
  - A step's `archetype` reference (W-6, shipped separately) is now load-bearing, not just
    shape-validated: a step that omits its own `gate` falls back to its resolved archetype's
    `gateContract` (`core.orchestrator.resolve_gate`).
  - `docket runs cancel <id>` (see `cli-interface.spec.md`) kills an in-flight hop's process group
    — the cancellation this spec's "Does NOT cover" previously deferred to W-2.
  - Pod provisioning/blueprints (W-7) remain the one still-unshipped "Does NOT cover" item.

### Version 1.0.1 (2026-07-30)

- ROADMAP Phase 16 W-3 (D-16) landed: `docket workflow`/Lobster was retired outright (a
  removed-command notice, not a migration onto this format) and workflow-integration.spec.md was
  deleted. Retargeted every cross-reference this spec had into that now-deleted file — no
  functional requirement in this spec changed; W-2 (the executor/CLI surface) remains unbuilt.

### Version 1.0.0 (2026-07-30)

- Initial specification. ROADMAP Phase 16, card W-1: the docket-native pipeline format —
  `PipelineSpec`/`Step`/`MechanicalGate`/`VerdictGate`/`ApprovalGate`/`ReworkEdge`/`Variable`
  (`core/pipeline.py`), unknown-key-rejecting at every level, bounded rework edges generalizing
  R-4's Reviewer→Implementer loop, `parallel` group shape, declared `variables`, shape-only
  `archetype` references (composing with the not-yet-built W-6 registry), and the zero-migration
  `default_pipeline()`/`load_pipeline(None)` contract equivalent to `core/dispatch.py`'s hardcoded
  `PIPELINE_ORDER`. No executor, CLI surface, or dry-run renderer ships with this version — see
  ROADMAP Phase 16 cards W-2/W-3.
