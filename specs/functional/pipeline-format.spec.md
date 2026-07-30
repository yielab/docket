# Pipeline Format Specification

**Version**: 1.0.0
**Status**: Implemented (format only — no executor; see "Does NOT cover")
**Last Updated**: 2026-07-30

## Purpose

This specification defines **the docket-native pipeline format**: a single, Pydantic-modeled,
unknown-key-rejecting YAML dialect describing how a pod's roles are ordered, gated, and (later)
run in parallel. It is ROADMAP decision D-16's replacement for the Lobster YAML dialect
(`workflow-integration.spec.md`) — docket lints Lobster but cannot execute four of the constructs
its own template emits; this format has no such gap because nothing in it is accepted that this
spec doesn't also define. The format is implemented by `core/pipeline.py`.

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
- The three gate kinds a step may declare: `mechanical` (a command), `verdict` (regex-matched
  marker output), and `approval`
- Bounded rework edges on a `verdict` gate (generalizing `core/dispatch.py`'s R-4 Reviewer →
  Implementer rework loop to an arbitrary earlier step and an arbitrary verdict vocabulary)
- `parallel` step groups — the data shape for concurrently-run child steps
- Pipeline-level `variables` (declared defaults / required placeholders — no interpolation engine)
- Loading a pipeline from YAML text, including the **zero-migration** built-in pipeline returned
  when no file exists
- Structural validation (`validate_pipeline`) and its error contract

This specification does NOT cover:

- **Execution.** No executor for this format exists yet. `core/pipeline.py` never runs a step,
  spawns a process, or contacts a daemon — it only parses and validates a document into typed
  Python objects. Running a `PipelineSpec` over the pod-dispatch state machine (`pod-dispatch.
  spec.md`), a bounded worker pool, per-step trace spans, and cancellation is ROADMAP Phase 16
  card **W-2**, tracked separately and not built by this card.
- **A CLI surface.** No `docket pipeline ...`/`docket workflow` command reads or writes this
  format yet; `docket workflow` still serves the Lobster dialect exactly as documented in
  `workflow-integration.spec.md` until W-2/W-3 retire it. This spec's functions are called
  directly by Python today, the same way `core/lobster.py`'s were before `cli/_workflow.py`
  existed.
- **A `plan`-style dry-render.** ROADMAP is explicit that `docket workflow plan` must eventually
  render from the real executor, not a second pretty-printer that can drift from it. Building one
  now — before an executor exists to drift from — would be exactly that drift-prone second
  printer, so none is built here.
- **The Lobster dialect itself**, its validator, or its retirement — see `workflow-integration.
  spec.md` and ROADMAP decision D-16 / Phase 16 card W-3.
- **Declarative role archetypes** (`archetype`'s registry: names, `modelClass`, `soulTemplate`,
  `gateContract`, …) — ROADMAP Phase 16 card **W-6**. This spec's `archetype` field validates only
  that a referenced name has archetype-slug *shape*; it never checks that the name exists in any
  registry, so the two cards compose without either depending on the other's code landing first.
- **Pod provisioning / blueprints** (which roles a pod actually has, `--count N` duplicate
  members, workspace kind) — see `workspace-structure.spec.md` and ROADMAP Phase 16 card W-7.
  This spec only defines how a *step* may target a role or a specific member id; whether that
  role or id exists in a given pod is resolved at dispatch time, by whatever dispatches it.
- **Approval-gated dispatch's runtime semantics** (tokens, timeout-resolves-to-denied, the
  CLI/HTTP grant/deny surface) — see `security-gates.spec.md` and ROADMAP Phase 15 card G-1. This
  spec only defines the `approval` gate's on-disk shape.

## Requirements

### Document shape

1. A pipeline document **MUST** be a YAML mapping with `extra="forbid"` semantics at *every*
   nesting level (the document itself, every step, every gate, every rework edge, every
   variable): an unrecognized key anywhere **MUST** be a validation error, never silently
   ignored. This is the specific gap this format closes relative to Lobster (`workflow-
   integration.spec.md`'s `validate` silently ignores `continueOnError`/`approval`/`outputs`/
   `notifications`).
2. A pipeline document **MUST** declare a non-empty `name` (`str`) and a non-empty `steps` list.
   `description` (`str`, default `""`) and `variables` (a mapping, default `{}`) are optional.

### Variables

1. Each entry in `variables` **MUST** be a mapping with an optional `default` (any YAML scalar or
   structure, default `None`), an optional `description` (`str`, default `""`), and an optional
   `required` (`bool`, default `False`).
2. A variable **MUST NOT** declare both `required: true` and a non-null `default` — a required
   variable has no default by definition; a value **MUST** come from whatever invokes the
   pipeline (e.g. a future W-4 webhook parameter).
3. A variable's key **MUST** be a valid identifier (`^[A-Za-z_][A-Za-z0-9_]*$`). No interpolation
   syntax or engine is defined by this spec — declaring a variable does not by itself cause any
   text substitution anywhere; that is an executor concern (W-2).

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
   case-normalization) — a marker cannot mean both "pass" and "rework" at once.
4. **`approval`** — an optional `message` (`str`, default `""`) shown to whoever grants the
   approval. This format defines only the gate's shape; wiring it to docket's approval store
   (tokens, grant/deny, timeout-resolves-to-denied) is Phase 15 G-1 / W-2's job, not this spec's.

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

### Parallel groups

1. A step **MAY** be a **parallel group** instead of a unit step: it sets `parallel` to a
   non-empty list of unit steps that (once an executor exists) run concurrently — e.g. one per
   `--count N` duplicate role member of a pod.
2. A parallel-group step **MUST NOT** also declare `role`, `agent`, `gate`, `retries`, or
   `timeout` at the group level — only its children carry those; declaring any of them on the
   group itself **MUST** be a validation error.
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
   — structural validation only, mirroring `core/lobster.py`'s `validate_lobster` contract for
   symmetry between the two (now sibling, soon-superseding) formats.
5. If PyYAML is unavailable, `load_pipeline`/`validate_pipeline` **MUST** report an actionable
   error (naming `pip install pyyaml`) rather than raising an unguarded `ImportError` — the same
   defensive-import convention `core/lobster.py` and `cli/_agents.py` already follow, even though
   PyYAML is a declared runtime dependency (`pyproject.toml`).

## Interface Contracts

This spec defines a Python data model and pure functions in `core/pipeline.py` — there is no CLI
surface yet (see "Does NOT cover").

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
  "valid but not fully checked" state, unlike Lobster's `validate` (`workflow-integration.
  spec.md`), which silently ignores several keys its own template emits.
- `default_pipeline()` itself satisfies every validator `PipelineSpec` enforces for a
  hand-authored file — it is not exempt from its own rules (test-pinned).

### Invariants

- Every level of the document (`PipelineSpec`, `Step`, `MechanicalGate`, `VerdictGate`,
  `ApprovalGate`, `ReworkEdge`, `Variable`) rejects unknown keys.
- `default_pipeline()`'s role order **MUST** equal `core/dispatch.py`'s `PIPELINE_ORDER` tuple,
  and its Reviewer/Tester `pattern` strings **MUST** equal `core/dispatch.py`'s own
  `_REVIEWER_VERDICT_RE`/`_TESTER_VERDICT_RE` patterns — checked directly, by test, against those
  constants (`tests/python/test_w1_pipeline_spec.py::TestZeroMigration`), not by hand-copied
  literals that could silently drift.
- No executor, CLI command, or dry-run renderer exists anywhere in this spec's contract — building
  one is explicitly out of scope (see "Does NOT cover").

## Changelog

### Version 1.0.0 (2026-07-30)

- Initial specification. ROADMAP Phase 16, card W-1: the docket-native pipeline format —
  `PipelineSpec`/`Step`/`MechanicalGate`/`VerdictGate`/`ApprovalGate`/`ReworkEdge`/`Variable`
  (`core/pipeline.py`), unknown-key-rejecting at every level, bounded rework edges generalizing
  R-4's Reviewer→Implementer loop, `parallel` group shape, declared `variables`, shape-only
  `archetype` references (composing with the not-yet-built W-6 registry), and the zero-migration
  `default_pipeline()`/`load_pipeline(None)` contract equivalent to `core/dispatch.py`'s hardcoded
  `PIPELINE_ORDER`. No executor, CLI surface, or dry-run renderer ships with this version — see
  ROADMAP Phase 16 cards W-2/W-3.
