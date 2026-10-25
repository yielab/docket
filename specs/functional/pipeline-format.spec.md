# Pipeline Format Specification

**Version**: 4.2.0
**Status**: Implemented. The document format, its validation, variable resolution, `${var}`
interpolation of step instructions, the short form, outcome routing, command, conditional and
operator-input steps and the external gate are all live. Running a pipeline is `pod-dispatch.spec.md`.
**Last Updated**: 2026-10-25

## Purpose

This specification defines **the docket-native pipeline format**: a single, Pydantic-modeled,
unknown-key-rejecting YAML dialect describing how a pod's roles are ordered, gated, routed and
(optionally) run in parallel. Nothing is accepted by the format that this specification does not
also define. The format owns *shape and validation*: what loads, and what a document means. What
happens when a loaded pipeline runs belongs to `pod-dispatch.spec.md`.

The **zero-migration contract** is this specification's central guarantee: a pod with no pipeline
file runs the built-in pipeline, lead -> implementer -> reviewer -> tester with the gates this
document lists. Installing the format changes nothing for an existing pod until an operator writes
a pipeline file.

## Scope

This specification covers:

- The `PipelineSpec` document shape: `name`, `description`, `variables`, `steps`
- Step targeting: a step names exactly one of a `role` or a specific `agent`, plus an optional
  `archetype` reference; and the two targetless step kinds, `run` (a command) and `input` (an
  operator question)
- Per-step `retries`, `timeout`, `instructions` and `model`
- The four gate kinds a step may declare: `mechanical` (a command), `verdict` (regex-matched marker
  output), `approval` and `external` (an operator command mapped through an exit-code table)
- Bounded `rework` edges on a `verdict` gate, and the general per-step `on` outcome routing
- `parallel` step groups
- Conditional steps (`when`) and command steps (`run`, `env`)
- Pipeline-level `variables`, their resolution and the interpolation of `${name}` references in step
  instructions
- The short form, the one authored spelling of a step, which expands to the in-memory model before
  validation; a step written in the canonical spelling (an `id:` key) is refused
- Loading from YAML text, including the built-in pipeline returned when no file exists, and the
  error contract of validation

This specification does NOT cover:

- **Execution.** Loading and validating never runs a step, spawns a process or contacts a model.
  Running a `PipelineSpec` (claiming, budget and approval gates, retries, crash resume, the
  `parallel` worker pool, trace events, cancellation, routing decisions, the failure kinds of a
  failed gate) is `pod-dispatch.spec.md`, in particular its "Generalized gate execution",
  "Conditional steps and command steps", "Parallel step groups", "Operator input steps and
  answers" and "Cancellation" sections.
- **The CLI surface** (`docket pod validate`, `docket pod plan`, `docket pod set pipeline`,
  `docket run --pipeline`/`--var`: argument shapes, exit codes): `cli-interface.spec.md`.
- **Configuration documents in general** (`kind:` envelopes, directory discovery, one validator per
  kind): `config-format.spec.md`. This specification covers only the `pipeline` kind's body.
- **Role archetypes** (the registry of names, `gateContract`, `hopInstruction`):
  `role-archetypes.spec.md`. A step's `archetype` field is validated for slug shape only; its
  existence, and the archetype `gateContract` used when a step omits its own `gate`, are resolved
  when a plan is built (`pod-dispatch.spec.md`).
- **Pod provisioning and blueprints** (which roles a pod has, `--count N` members, workspaces):
  `workspace-structure.spec.md`, `pod-blueprints.spec.md`. A step may name any role or member id;
  whether it exists in a given pod is a plan-time concern.
- **Approval runtime semantics** (tokens, timeout resolving to denied, the grant and deny surface):
  `security-gates.spec.md` and `pod-dispatch.spec.md`. This specification defines only the
  `approval` gate's shape.
- **Shipped recipe bundles**: a recipe's `pipeline.yaml` is an ordinary document this format
  validates like any hand-written file; the bundle contract is `role-archetypes.spec.md`'s
  "Shipped recipes".

## Requirements

A pipeline file is authored in the short form ("Short form") and in no other. The requirements
below name the fields of the in-memory model (`PipelineSpec`, `Step`, the gates) that each short
step expands to; the canonical spelling of that model (a step with an `id:` key, a gate with
`type:`) is never read from a file.

### Document shape

1. A pipeline document **MUST** be a YAML mapping with `extra="forbid"` semantics at *every* level of
   the model (the document, every step, every gate, every rework edge, every variable, every `when`,
   every `input`): an unrecognized key anywhere **MUST** be a validation error, never silently
   ignored.
2. A pipeline document **MUST** declare a non-empty `name` (`str`) and a non-empty `steps` list.
   `description` (`str`, default `""`) and `variables` (a mapping, default `{}`) are optional.
3. A pipeline document **MAY** declare a top-level `kind: pipeline`; loading strips it before
   validation, and any other `kind` value is a load error naming `pipeline` as the expected value.
   A document with no `kind` loads exactly the same way.

### Variables

1. Each entry in `variables` **MUST** be a mapping with an optional `default` (any YAML value,
   default `None`), an optional `description` (`str`, default `""`) and an optional `required`
   (`bool`, default `False`).
2. A variable **MUST NOT** declare both `required: true` and a non-null `default` — a required
   variable has no default by definition; its value **MUST** come from whatever invokes the
   pipeline.
3. A variable's key **MUST** be a valid identifier (`^[A-Za-z_][A-Za-z0-9_]*$`). Declaring a
   variable causes no substitution by itself; a step substitutes by referencing `${name}` in its
   `instructions` (Steps Requirement 8, Requirement 5 below). A name the `variables` map never
   declares may still be referenced, as long as the run's resolved namespace supplies it
   (Requirement 4's pass-through rule).
4. **Variable resolution.** `resolve_variables(spec, provided)` **MUST** produce the pipeline's
   final `{name: value}` namespace from a caller-supplied *provided* mapping (the dispatch
   webhook's JSON object body, see `serve-read-api.spec.md`; or the repeatable
   `docket run --var key=value`, see `cli-interface.spec.md`):
   - a name present in *provided* **MUST** win outright, whatever its value — an explicit `null`
     counts as supplied, not absent;
   - a name declared in `variables` but absent from *provided* **MUST** fall back to that
     variable's `default` (`None` when it has none);
   - a `required` variable absent from *provided* **MUST** raise `VariableError`; every missing
     required name **MUST** be named in the one raised error;
   - a key present in *provided* but not declared **MUST** pass through unchanged — resolution
     validates the *presence* of required values, not a closed key set (unlike the document shape).
   Resolution itself interpolates nothing; it only produces the namespace Requirement 5 reads.
5. **Step instruction interpolation.** A step's `instructions` may reference `${name}` placeholders —
   the exact `${name}` spelling only; a bare `$name` or a literal `$` (a dollar amount) is never a
   placeholder. Before any hop runs, a dispatch **MUST** resolve the run's namespace
   (Requirement 4) and check every step's `instructions` (including `parallel` children) for a
   `${name}` reference the namespace does not resolve (`unresolved_step_variables`, sorted and
   deduplicated); if any exist the whole run **MUST** be refused — no task claimed, no hop run —
   naming every unresolved name at once. A task that names its own pipeline fails the same way at
   claim (`pod-dispatch.spec.md`, "Pipeline order and participation"). Once resolved,
   `interpolate_instructions(text, variables)` substitutes each reference with the value's string
   form; a reference it cannot resolve is left literal. See `role-archetypes.spec.md`'s "Hop
   instructions" for how the interpolated text interacts with a role's own instruction.

### Steps

1. Each entry in `steps` **MUST** have a non-empty, pipeline-unique `id` (`str`). Uniqueness
   **MUST** be checked across every step id in the document, including every child of every
   `parallel` group — a duplicate anywhere **MUST** be a validation error.
2. A **unit step** (one not using `parallel`) **MUST** target exactly one of `role` (`str`) or
   `agent` (`str`) — declaring both, or neither, **MUST** be a validation error — unless it is a
   command step (`run`, Requirement 9) or an operator-input step (`input`, "Operator input steps"),
   which are exclusive of `role` and `agent`.
3. `role` **MUST** be a lowercase slug (`^[a-z][a-z0-9_-]*$`). The format does **not** restrict
   `role` to the four built-in roles (`lead`/`implementer`/`reviewer`/`tester`); any slug-shaped
   value validates, since whether it names a role a given pod has is a plan-time concern.
4. `agent` **MUST** be a non-empty string (a specific member id, e.g. `myapp-implementer-2`); the
   format does not check that the id exists or belongs to any pod.
5. A step **MAY** declare `archetype` (`str`), a plain reference to a role archetype name. It
   **MUST** be a lowercase slug (the shape of `role`); its *existence* against the archetype
   registry is explicitly **NOT** checked by the format (see Scope).
6. A step **MAY** declare `retries` (`int`, `>= 0`) and/or `timeout` (`int`, `> 0`, seconds).
   Omitting either (`None`, the default) **MUST** mean "defer to the role-level or pod-level default
   the executor applies" (`pod-dispatch.spec.md`: "Retries and the failure-kind taxonomy",
   "Timeout configuration").
7. A step **MAY** declare a `gate` (see "Gates") or omit one (no gate: the step advances once its
   turn completes, as the built-in Lead step does).
8. A unit step **MAY** declare `instructions` (`str`), its own hop instruction, overriding whatever
   the target role would otherwise carry (a built-in role's text, or a custom role's own
   `hopInstruction` or generated fallback; `role-archetypes.spec.md`, "Hop instructions"). Omitting
   it (`None`, the default) means "defer to the role", not "no instruction". It **MAY** reference
   `${name}` variables (Variables Requirement 5). A step targeting `role: lead` **MUST** have its
   `instructions` applied like any other role: they replace the Lead's own instruction text (the
   built-in line, or an overlaid `lead` archetype's `hopInstruction`).
9. A unit step **MAY** declare `run` (`str`, a shell command) instead of `role`/`agent`; declaring
   `run` beside either, or beside `input`, **MUST** be a validation error. A `run` step (a command step) **MUST NOT**
   also declare `gate`, `instructions`, `retries`, `archetype` or `model`; each is a validation
   error naming the field. It **MAY** declare `timeout`, `when` and `on` (see "Conditional steps and
   command steps" and "Outcome routing"). Its exit code is its own outcome; the format models no
   `gate` for it. A `run` step **MAY** declare `env` (`dict[str, str]`, "Conditional steps and
   command steps" Requirement 4); `env` on any other step kind, including a `parallel` group,
   **MUST** be a validation error. An empty or blank `run` **MUST** be a validation error.
10. A unit step **MAY** declare `model` (`str`): one of the rank words `cheap`/`strong`, or a
    `<provider>/<id>` literal (a non-empty segment either side of the first `/`). It overrides the
    model this hop's target would otherwise run on, for that hop only (`pod-dispatch.spec.md`,
    "Per-hop execution"; `model-profiles.spec.md`, "Where a member's model comes from"). Loading
    validates only the literal's *shape*. Whether a `<provider>/<id>` literal's provider exists in
    the provider catalog is checked when a document is validated as a file (`docket pod validate`
    and `docket pod plan --pipeline` refuse an unknown provider) and when the hop runs
    (`pod-dispatch.spec.md`, "Per-hop execution"), never by loading text. Omitting `model` (`None`, the default) means "defer to the role/pin/policy
    resolution that already applies". A parallel group **MUST NOT** declare `model` at the group
    level (only its children may).

### Gates

1. A `gate` **MUST** be one of exactly four kinds, discriminated by its own `type` field:
   `mechanical`, `verdict`, `approval` or `external`. An unrecognized `type` **MUST** be a
   validation error.
2. **`mechanical`** — `command` (`str | None`, default `None`) and `timeout` (`int | None`, `> 0` if
   given). A non-zero exit from `command` fails the step. `command: None` **MUST** mean "defer to
   the target agent's own configured check" (the Implementer's `verifyCmd`, see
   `docket-meta.spec.md`), not "no check"; this is what lets the built-in pipeline express the
   default Implementer gate without inventing a command.
3. **`verdict`** — `pattern` (`str`, a non-empty, compilable regular expression whose first
   capturing group is the verdict marker), `passValues` (`list[str]`, non-empty), `caseSensitive`
   (`bool`, default `false`) and an optional `rework` edge ("Rework edges"). A matched marker
   (normalized per `caseSensitive`) present in `passValues` **MUST** allow the pipeline to advance;
   a marker matched by `rework`'s `when` list **MUST** trigger a bounded rework cycle; any other
   outcome — including no match (unparseable output) — **MUST** fail the step, unless the step's
   own `on` map names the marker ("Outcome routing"). `passValues` and `rework.when` **MUST NOT**
   share any value (after the same case-normalization). Each non-blank output line **MUST**
   be normalized before the pattern is applied: the line is stripped; leading markdown decoration
   (`*`, `_`, `#`, `-`, `>`, backticks and whitespace) and a leading `Verdict:` label (any case,
   with decoration around the colon) are removed; trailing decoration (`*`, `_`, backticks, `.`
   and whitespace) is removed. The documented aliases `APPROVED` (for `APPROVE`) and
   `REQUEST CHANGES` (for `REQUEST-CHANGES`) are read as their canonical word when they are the
   whole normalized line or are followed by `:`, `.` or `-`; an alias counts only for a gate whose
   pattern accepts the canonical word, and it keeps the gate's own case rule. The pattern **MUST**
   then be applied independently at the start of every normalized line; each first capture is
   normalized per `caseSensitive`. When the lines carry different values, the **last** matching
   line is the verdict; repeated matches of one value are that value. Zero matches is
   unparseable. A marker mentioned later in prose is not a match, and scanning never falls back to
   substring search.
4. **`approval`** — an optional `message` (`str`, default `""`) shown to whoever grants the
   approval. The format defines only the gate's shape; its runtime is `pod-dispatch.spec.md`
   ("require_approval gate and waiting_approval") and `security-gates.spec.md`.
5. **`external`** (ADR 0025) — `command` (`str`, required, non-empty), `timeout` (`int | None`,
   `> 0` if given) and `exitMap` (`{pass, fail, needs_human}`, each a non-empty list of exit codes,
   default `{pass: [0], fail: [1], needs_human: [2]}`; the three lists **MUST** be disjoint and
   exactly those three keys). The command is an operator string run after the step's hop; the code
   never names a verifier. The gate has four outcome labels: `pass`, `fail`, `needs_human` and
   `error`; an exit code in no list, a timeout, a jail refusal and a missing command are `error`.
   An external gate runs only its `command`; the member's `verifyCmd` is not run. It is a
   pipeline-step gate only: a role's `gateContract` never resolves to it. A step with an external
   gate **MAY** write `gate: {external: "<command>"}` (the short spelling), in a short or a
   canonical step; it normalizes to `{type: external, command: "<command>"}` and an unknown key
   beside `external` is a validation error. Execution and failure kinds are `pod-dispatch.spec.md`,
   "Generalized gate execution".

### Rework edges

1. A `rework` edge on a `verdict` gate **MUST** have a `to` (`str`, a non-empty step id), a `when`
   (`list[str]`, non-empty: the verdict marker values that trigger the edge) and a `maxCycles`
   (`int`, `>= 0`, default `1`).
2. `maxCycles: 0` **MUST** be a valid, meaningful value: it declares the edge but disables it (the
   gate is a hard block on every `when` value, as the built-in Tester gate is). A gate with no
   rework at all simply omits `rework`; both are valid, distinct ways to say "no rework".
3. The field is named `when`, not `on`, deliberately: YAML 1.1's implicit-boolean resolver (PyYAML's
   `safe_load`) parses a bare `on:` key as the boolean `True` unless quoted. Naming the field `when`
   avoids the trap rather than asking every author to quote a key.
4. `to` **MUST** name an existing **top-level** step id (not one nested inside a `parallel` group)
   that occurs **strictly earlier** in `steps` than the step declaring the edge. A non-existent id,
   a step at or after the declaring step's own position, or a step nested inside a `parallel` group
   **MUST** be a validation error. A top-level `parallel` group itself is a valid target.
5. A step nested inside a `parallel` group **MUST NOT** declare a `rework` edge on its own gate; the
   validation error names the offending child step.
6. `rework` **MUST** remain the canonical spelling of the one bounded backward verdict edge to an
   earlier step; the more general `on` field ("Outcome routing") reaches a later step, a
   `fail`/`stop` terminal, or more than one outcome label, without replacing it.

### Parallel groups

1. A step **MAY** be a **parallel group** instead of a unit step: it sets `parallel` to a non-empty
   list of unit steps that the executor runs concurrently (`pod-dispatch.spec.md`, "Parallel step
   groups"), for example one per `--count N` duplicate role member.
2. A parallel-group step **MUST NOT** also declare `role`, `agent`, `gate`, `retries`, `timeout`,
   `instructions`, `model`, `on`, `env`, `run`, `input`, `when` or `archetype` at the group
   level — its children carry the hop fields; declaring any of them on the group **MUST** be a
   validation error naming the field. An empty `parallel` list **MUST** be a validation error.
3. Nesting **MUST** be limited to exactly one level: a child of a `parallel` group **MUST NOT**
   itself declare `parallel`. A nested `parallel` **MUST** be a validation error naming the
   offending child.
4. Each child **MUST** independently satisfy the unit-step requirements above (a document-unique
   `id`, a valid target, valid `archetype`/`retries`/`timeout`/`instructions`/`model`/`gate`
   shape), except that a child's gate **MUST NOT** carry a `rework` edge (Rework edges
   Requirement 5). A group is written `- <id>: {parallel: [...]}` and each child is a short step
   (`- <child id>: <role or agent>` with its own sugar keys); the group carries nothing else. The
   executor runs a child as a plain role or agent hop and acts on none of
   `run`, `input`, `when` and `on` there, so a child **MUST NOT** declare any of them; each is a
   validation error naming the child and the field (a child's unquoted `on:` key is read as `on`).

### Zero migration

1. Loading with no supplied text (`text=None`: the caller found no pipeline file for this pod)
   **MUST** return the built-in `PipelineSpec` (named `default`, `source == "builtin"`): Lead (no
   gate) -> Implementer (`mechanical` gate, `command: None`, deferring to the target's own
   `verifyCmd`) -> Reviewer (`verdict` gate, pattern `^\s*(APPROVE|REQUEST-CHANGES)\b`,
   `passValues: [approve]`, a `rework` edge to `implementer` on `request-changes` with
   `maxCycles: 1`) -> Tester (`verdict` gate, pattern `^\s*(PASS|FAIL)\b`, `passValues: [pass]`, no
   rework).
2. This built-in pipeline **MUST** agree with what the dispatcher treats as the default pod
   pipeline: its role order **MUST** equal the dispatcher's built-in role order, and a bare
   `role: reviewer` or `role: tester` step with no `gate` of its own **MUST** resolve (through the
   role archetype's `gateContract`) to a verdict gate with the byte-identical `pattern` and
   case-insensitively equal `passValues` that the built-in pipeline's explicit gates declare. Both
   equivalences are drift-guarded by tests, not merely documented.
3. Loading an explicitly **empty** string (an existing but empty file) **MUST NOT** be treated as
   the zero-migration case — it **MUST** be a validation error (an empty document), distinct from
   "no file at all".
4. A pod whose roster lacks a role the built-in pipeline names (a lean pod with no Reviewer or
   Tester) is unaffected by the format: a step whose role has no member is skipped when the plan is
   built (`pod-dispatch.spec.md`, "Pipeline order and participation"); the built-in pipeline always
   names the full four-role sequence.

### Loading and validation

1. `load_pipeline(text)` **MUST** return a result carrying exactly one of: a validated
   `PipelineSpec` (`errors == []`), or a non-empty list of human-readable error strings
   (`spec is None`). It **MUST** also report its `source` — `"builtin"` for the zero-migration case,
   `"file"` otherwise — and an `ok` flag that is true exactly when the spec loaded.
2. A YAML parse error, an empty document, or a document that is not a mapping **MUST** each produce
   exactly one descriptive error string and no `spec`.
3. A schema violation (unknown key, missing required field, wrong type, a target-exclusivity
   violation, a duplicate id, a rework or routing violation, ...) **MUST** produce a non-empty
   error list. A violation of a single field's schema **MUST** be reported as one string led by the
   field's dotted location (`steps.0.timeout: ...`). A rule that spans steps (a duplicate id, a
   rework or `on` target, an unreachable step, an `input` source) **MUST** be reported as a string
   led by `<root>:` whose message names the offending step.
4. If PyYAML is unavailable, `load_pipeline` **MUST** report an actionable error (naming
   `pip install pyyaml`) rather than raise an unguarded `ImportError`, although PyYAML is a declared
   runtime dependency.

### Short form

1. `normalize_pipeline(doc: dict) -> dict` **MUST** be a pure function: given a parsed YAML document
   it returns the mapping `PipelineSpec` validates, without touching the filesystem or mutating
   its argument. `load_pipeline` **MUST** call it on every document (after stripping a
   `kind: pipeline` key) before `PipelineSpec` validation. A step written with an `id:` key (the
   canonical spelling, which is the in-memory model and never an authored form) **MUST** be a load
   error naming the step and the short spelling to use (`- <id>: <role>`, `{run: ...}`,
   `{input: ...}` or `{parallel: [...]}`).
2. A `steps` entry **MUST** be a mapping with exactly one key that is not one of the sugar keys
   below (`verify`, `verdict`, `approval`, `gate`, `instructions`, `timeout`, `retries`, `model`,
   `archetype`, `when`, `on`, `until`, `max`), so a step id cannot be a sugar key's name; that key
   becomes the step's `id`. Its value is a string (a role or agent step, Requirement 3) or a mapping
   carrying `run`, `input` or `parallel` (a command, input or parallel-group step). Any other shape
   **MUST** be a load error naming the step. A command or input step's mapping carries the
   canonical step's own keys unchanged (an unknown key is rejected by validation); a `parallel`
   group's mapping carries only `parallel`.
3. The target string **MUST** become `role:` when it is one of `lead`/`implementer`/`reviewer`/
   `tester`, or when it is not shaped like a pod member id; it **MUST** become `agent:` when it is
   shaped like one — `<prefix>-<role>` or `<prefix>-<role>-<index>` where `<role>` is one of the
   four base roles — recognized by shape alone, as the `archetype` field's slug shape is, without
   consulting any registry. `security-vetter` is therefore a `role:` (its last segment, `vetter`, is
   not a base role); `myshop-implementer` and `myshop-implementer-2` are `agent:`.
4. The recognized sugar keys, each optional, **MUST** be mapped as follows:
   - `verify: true` -> `gate: {type: mechanical}`; `verify: "<command>"` -> `gate: {type:
     mechanical, command: "<command>"}`; `verify: {command: "<command>", timeout: <n>}` carries
     the gate's own `command` and `timeout` (any other key is a load error).
   - `verdict: [<marker>, ...]` (at least one marker) -> `gate: {type: verdict, pattern:
     '^\s*(<marker>|...)\b', passValues: [<first marker, lowercased>]}`, each marker escaped for
     regex safety; the first marker is the passing value, the rest are outcomes a step's `on:` or an
     unparsed non-match may still fail on, exactly as the canonical `verdict` gate does. An empty or
     non-list `verdict` yields an invalid gate and so a validation error.
   - `approval: "<message>"` -> `gate: {type: approval, message: "<message>"}`.
   - `gate: {external: "<command>"}` -> `gate: {type: external, command: "<command>"}`, with
     optional `timeout` and `exitMap` carried to the gate's own fields; any other shape of the
     short `gate` key is a load error naming the step.
   - `instructions`, `timeout`, `retries`, `model`, `archetype`, `when` carry straight through to
     the same-named canonical field.
   - `on: {<label>: {goto: <earlier step id>, max: <n>}}` **MUST**, when the step also carries a
     `verdict` sugar key, the `on` mapping has exactly that one entry whose keys are only `goto` and
     `max`, and `goto` names an earlier step, become that gate's `rework: {to: <goto>, when:
     [<label, lowercased>], maxCycles: <n>}`; a `goto` to an earlier step without `max` is a load
     error naming the step. Because PyYAML reads an unquoted `on:` key as the boolean `True`, the
     sugar key **MUST** be accepted spelled either `"on"` or as the boolean `True`, on short and on
     steps alike. Every other `on:` shape **MUST** become the step's canonical
     `on` field verbatim ("Outcome routing"), never a load error of its own.
   - `until: "verify"` with a `max` sugar key **MUST**, on a step whose gate is `mechanical`, become
     `on: {fail: {goto: <this step's own id>, max: <n>}}` — a bounded self-retry. `until`/`max` are
     short-form only: the canonical form never carries `until`. `max` without `until`, an `until`
     other than `verify`, `until` without `max`, or `until` on a step with no mechanical gate
     **MUST** each be a load error naming the step; `until`/`max` **MUST NOT** be combined with an
     `on:` sugar key on the same step.
   - A step carrying more than one of `verdict`, `verify`, `approval` and `gate` **MUST** be a load
     error naming the step and the keys (`step 'build': one gate per step (got verify, gate)`),
     never one gate kept and the rest dropped.
   - A step carrying no gate sugar key **MUST** get no `gate` at all: the target role's own
     contract applies, exactly as for a canonical step with no `gate`.
5. A **command step** is written `- <id>: {run: "<command>", timeout: <n>, when: {...}, env: {...}}`
   and an **input step** `- <id>: {input: {from: <step id>, message: "..."}, on: {...}}`; each
   expands to the canonical `{id, run, ...}` or `{id, input, on}` step. Their keys live inside the
   mapping value, not beside the id. Keys other than the ones shown are carried only where the
   canonical step defines them (an unknown key is rejected by validation).

### Outcome routing

1. A step **MAY** declare `on` (`dict[str, Route] | None`), a canonical field beside `gate`: a
   mapping from an outcome label to a `Route`. The label vocabulary is the step's own: a verdict
   gate's matched marker; `pass`/`fail` for a mechanical gate; `pass`/`fail`/`needs_human`/`error`
   for an external gate (any other key on an external-gated step **MUST** be a validation error);
   `answered`/`declined` for an `input` step (any other key **MUST** be a validation error); for a
   `run` step, `pass`/`fail` by exit code, or the command's last non-blank output line when that
   line is a single upper-case token. Labels are compared case-insensitively. A `Route` is either a
   mapping `{goto: <step id>, max: <int>}` (`max`, wherever it is written, **MUST** be an integer
   `>= 1`, and **MUST** be present when `goto` names a step at or before this one) or one of the literal strings `"fail"` or `"stop"`, or a bare step id
   (a forward target equivalent to `{goto: <that id>}` with no bound). A route mapping with any
   other key, or a route of any other type, **MUST** be a validation error.
2. A gate outcome named in the step's own `on` map is routed *instead of* that outcome's ordinary
   handling: `fail` fails the task, `stop` ends it `done`, a step id continues the pipeline there (a
   backward or self target counted against its own `max`). An outcome the map does not name behaves
   as it always has. How a routing decision is executed, counted and traced is
   `pod-dispatch.spec.md`, "Generalized gate execution".
3. `PipelineSpec` **MUST** validate every top-level step's `on` entries: a `goto` or bare step id
   **MUST** name an existing top-level step id in the document (forward or backward) or be
   `fail`/`stop`; a `max` that is not an integer `>= 1`, or a backward or self target without one,
   **MUST** be a validation error naming the step; and a step that no execution path reaches **MUST** be a validation error naming
   the unreachable step. The reachability walk starts at the first step, follows each step's default
   successor and every `on` target, and never continues past a `fail`/`stop` terminal; a step's
   default successor edge is not followed when its `on` map names every outcome that would
   advance it (`pass` and `fail` for a mechanical gate, every `passValues` entry for a verdict gate,
   `pass` for an external gate). `docket pod plan` renders every step's routes beside its gate.
4. The one recognized single-bounded-backward-edge shorthand ("Short form") **MUST** keep
   normalizing to the canonical `rework:` edge, never to `on`, so every rework-based document and
   the shipped recipes stay byte-identical.
5. A backward or self route out of a `mechanical` or `external` gate that did not pass (for example
   `until: verify`) **MUST** tell the target's next hop why the gate failed
   (`pod-dispatch.spec.md`, "Bounded hop prompts": the `--- GATE FAILED: <step id> ---` section). A
   forward route, a backward `pass` route and a verdict gate's route add no such section.
6. An external gate's `fail`, `needs_human` and `error` outcomes each **MAY** be routed by the
   step's `on` map; an outcome the map does not name and that is not `pass` fails the task with a
   gate failure kind (`pod-dispatch.spec.md`, "Generalized gate execution" item 6).
   `on: {needs_human: <input step>}` parks the task on an existing `input` step whose
   `answered`/`declined` route on.
7. A step with a `mechanical` or `external` gate that routes any outcome to the `input` step
   immediately after it **MUST** also route `pass` (for example `pass: stop`, or the step that
   should follow), or loading **MUST** refuse the pipeline: otherwise a pass would take the default
   edge into that `input` step and park the task again. A `verdict` gate names its own passing
   values and is not held to this rule.

### Conditional steps and command steps

1. Any step (unit or command) **MAY** declare `when` (ADR 0010): a closed predicate vocabulary, never a general
   expression language — `changed` (`str`, a glob matched against the working tree's changed
   paths), `var` (`str`, a pipeline variable name) paired with `is` (`str`, its expected resolved
   string form), and `memberPresent` (`str`, a pod role). `var` and `is` **MUST** be set together;
   one without the other is a validation error. At least one predicate **MUST** be set; `when` with
   none is a validation error. More than one predicate **MUST** mean every one is ANDed — the
   format defines no `anyOf`/`not` for `when`, the closed-vocabulary posture of
   `security-gates.spec.md`'s policy predicates. A false predicate skips the step; the
   skip and its trace are `pod-dispatch.spec.md`, "Conditional steps and command steps".
2. `run` (Steps Requirement 9) is the command step: a plain shell command string run with no agent
   turn at all. Its `timeout` (if set) bounds the command as a `mechanical` gate's `timeout` bounds
   a verify command. Its outcome is its exit code, or, when the step declares `on`, the label of
   Outcome routing Requirement 1; both are execution concerns the format does not model as a
   `gate`.
3. A `when` or `run` shape violation **MUST** be reported like any other schema violation
   (Loading and validation Requirement 3). `docket pod plan`'s rendering of `run` and
   `when`-bearing steps comes from the real executor's plan renderer (`cli-interface.spec.md`); the
   format defines no renderer.
4. A command step's `env` maps names to string values passed to the command's process (merged under
   the task coordinates, `pod-dispatch.spec.md`). Each name **MUST** match `^[A-Z][A-Z0-9_]*$`;
   `PATH`, `BASH_ENV`, `ENV`, any `LD_*`, `PYTHON*` or `DOCKET_*` name, and any name the process
   credential strip treats as a credential **MUST** be a validation error naming the entry; a
   non-string value **MUST** be a validation error. It is written inside a short command step
   (`- lint: {run: ..., env: {...}}`), is carried on the planned step, and survives `pod export`
   because the bound pipeline is exported verbatim.

### Operator input steps

1. `input` is the operator-input step: a pipeline pause that asks the operator a question. It names
   a prior step as its `from:` source and **MAY** declare a `message`
   (`str`, the question) and `expiresHours` (`int`, `> 0`, how long an answer is valid). An `input`
   step **MUST NOT** declare `role`, `agent`, `gate`, `retries`, `timeout`, `instructions`, `model`
   or `env`. Its `on` routing, when present, **MUST** use only the keys `answered` or `declined`
   (case-insensitive).
2. `input.from` **MUST** be the id of a *top-level* step that precedes this one in the pipeline; a
   forward or self reference, or an id that is not a top-level step id, is a validation error
   naming the step id and the bad source.
3. `docket pod plan` renders an `input` step as `asks the operator (from <source-step-id>)`; the
   plan only describes the step, it never asks.
4. Execution — parking the task in `waiting_input` and resuming from an operator's answer — is
   `pod-dispatch.spec.md`, "Operator input steps and answers" and "Task status vocabulary".
5. **An `input` step needs a person, so it needs level `L3`.** A pipeline asks a person by design, and
   a task whose autonomy level (`security-gates.spec.md` "Autonomy levels") does not let a person
   be asked has nobody to answer. The rule is exact: a task is refused when its effective level's
   `input` row in the autonomy table is not `person` (`L4` and `L5` in the built-in table) and the
   pipeline it runs holds at least one `input` step (a `parallel` child cannot carry one). The check is `input_refusal(spec, level)`, run when the task is claimed, with the same
   validation that resolves its variables: the task fails before any hop with `failureKind:
   "pipeline"` and a `reason` naming the step ids, the level and the two ways out (lower the
   task's `autonomy` to `L3`, or take the step out). The pipeline file itself stays valid:
   `docket pod validate` and `docket pod plan --pipeline` have no task and do not apply the rule.

## Interface Contracts

The format is a Python data model plus pure functions. The CLI surface that reads it is in
`cli-interface.spec.md`: `docket pod validate`, `docket pod plan [--pipeline FILE]` and
`docket run --pipeline FILE`. `docket pod plan` **MUST** resolve the pod's bound or default
pipeline (or FILE, validated by the same validator as `docket pod validate`, refusing a step `model`
naming an unknown provider) against the live roster and print the real executor's rendering of the
resulting plan, starting nothing and spending no tokens. A caller that validates a file for
**storage** is `docket pod set pipeline <file>`: it loads the file, plans it against the pod's
roster, and only then persists a copy (`pod-dispatch.spec.md`, "Pipeline order and participation"
Requirement 6). The format itself gains no field and no storage concept from that caller.

Loading and the built-in pipeline:

```python
result = load_pipeline(text_or_none)
result.ok        # bool: spec is not None and errors == []
result.spec      # PipelineSpec | None
result.errors    # list[str]
result.source    # "file" | "builtin"

builtin = default_pipeline()       # the zero-migration PipelineSpec, unconditionally
```

Short form:

```python
normalize_pipeline(doc)   # dict -> dict: short-form steps expanded into the mapping
                          # PipelineSpec validates; a canonical step (an `id:` key) is refused.
                          # load_pipeline calls this before PipelineSpec validation;
                          # callers of load_pipeline never need to call it themselves.
```

Variable resolution:

```python
values = resolve_variables(spec, provided)   # provided: dict[str, Any] | None
# -> dict[str, Any]: every declared variable resolved (provided value, else default),
#    plus any undeclared key from `provided` passed through unchanged.
# Raises VariableError naming every missing `required` variable at once.
```

Step instruction interpolation:

```python
step_instructions_by_id(spec)              # -> dict[str, str]: step id -> its own declared
                                           #    `instructions`, not yet interpolated (a step
                                           #    with none is absent; children included)
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
  - plan: lead
  - build: implementer
    verify: "pytest -q"
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
  - plan: lead
  - fanout:
      parallel:
        - impl-a: myapp-implementer
          instructions: "Focus on ${TARGET}."
        - impl-b: myapp-implementer-2
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: fanout, max: 2}}
  - ship: implementer
    approval: "Ready to deploy?"
```

### The short form: a bounded self-retry, a rework edge, a command step and an input step

```yaml
name: checked
variables:
  AREA: {default: api}

steps:
  - plan: lead
  - build: implementer
    verify: "pytest -q"
    until: verify
    max: 2
    instructions: "Change only ${AREA}."
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {request-changes: {goto: build, max: 1}}
  - lint: {run: "ruff check .", timeout: 120, when: {changed: "*.py"}}
  - ask: {input: {from: review, message: "Ship it?"}, on: {declined: fail}}
```

`build` expands to a `mechanical` gate plus `on: {fail: {goto: build, max: 2}}`; `review` expands to
a `verdict` gate with a `rework` edge to `build`, not to `on`.

### An unknown key is rejected, not ignored

```yaml
name: broken
steps:
  - build: implementer
    verifyCommand: "pytest -q"   # typo: not a real field
```

```text
>>> load_pipeline(text).errors
["a step needs exactly one key that is not a sugar key, the step id (got 'build', 'verifyCommand'); write '- <id>: <role>'"]
```

### A canonical step is refused, naming the short spelling

```yaml
name: old
steps:
  - id: build
    role: implementer
```

```text
>>> load_pipeline(text).errors
["step 'build' is written in the canonical form (an 'id:' key); write the id as the key: '- build: <role>', ..."]
```

## Validation

### Pre-conditions

- The caller has already decided whether a pipeline file exists for the pod in question; loading
  performs no filesystem I/O. Passing `None` is how a caller expresses "no file".

### Post-conditions

- A successfully loaded `PipelineSpec` satisfies every requirement in this document that states a
  validation error.
- `default_pipeline()` satisfies every validator `PipelineSpec` enforces for a hand-written file;
  it is not exempt from its own rules (test-pinned).

### Invariants

- Every level of the model (`PipelineSpec`, `Step`, `MechanicalGate`, `VerdictGate`, `ApprovalGate`,
  `ExternalGate`, `ReworkEdge`, `Variable`, `When`, `InputSpec`) rejects unknown keys.
- `default_pipeline()`'s role order **MUST** equal the dispatcher's built-in role order, checked
  directly by a test rather than against a hand-copied literal. Its Reviewer and Tester gates
  **MUST** equal the gates the role archetypes' `gateContract` resolve to for a bare `reviewer` and
  `tester` step (same pattern, case-insensitively equal `passValues`, both `caseSensitive: false`).
- Loading contains no executor, CLI command or plan renderer: those are the dispatcher, the
  orchestrator's plan functions and the `pod` commands.

## Implementation

Where the names used above live today.

- `src/docket/pipeline/domain/spec.py`: `PipelineSpec`, `Step`, `MechanicalGate`, `VerdictGate`,
  `ApprovalGate`, `ExternalGate`, `ReworkEdge`, `Variable`, `When`, `InputSpec`, `VariableError`,
  `PipelineLoadResult`, `load_pipeline`, `normalize_pipeline`, `default_pipeline`,
  `resolve_variables`, `step_instructions_by_id`, `unresolved_step_variables`,
  `interpolate_instructions`
- `src/docket/pipeline/domain/plan.py`: `resolve_gate`, `resolve_plan`, `render_plan`, `parse_verdict`
  (the verdict-line rule of Gates Requirement 3), `run_group`; it holds no step loop
- `src/docket/hops/application/steps.py`: `PIPELINE_ORDER`, `effective_pipeline`,
  `_run_command_step` (`_command_outcome_label`)
- `src/docket/hops/application/sweep.py`: `dispatch_pod` (the unresolved-variable refusal)
- `src/docket/hops/application/executor.py`: `_run_pipeline` (the step loop), `_route_outcome`
- `src/docket/teams/config_docs.py`: `validate_path`, `load_document` (`docket pod validate`, and the
  provider-existence check of a step `model`)
- `src/docket/teams/roles.py`: the `gateContract` fallback used by the Zero migration invariant
- `src/docket/interfaces/cli/commands/pod_config.py`: `docket pod plan`; `src/docket/interfaces/cli/commands/pod.py`:
  `docket pod set pipeline`; `src/docket/interfaces/cli/commands/run.py`: `docket run --pipeline`/`--var`
- `src/docket/interfaces/http/routes/dispatch.py`: the dispatch webhook's variable resolution
- `src/docket/sandbox/launch.py`: `credential_names` (the credential strip used by `env`)
- `tests/unit/pipeline/domain/test_spec__spec.py` (`TestZeroMigration` and the format),
  `tests/unit/pipeline/domain/test_spec__external_gate.py`, `tests/unit/pipeline/domain/test_spec__step_env.py`,
  `tests/unit/pipeline/domain/test_spec__webhook_variables.py`, `tests/integration/teams/test_archetypes.py`
