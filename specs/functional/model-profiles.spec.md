# Model Policy Specification

**Version**: 2.1.0
**Status**: Complete
**Last Updated**: 2026-07-02

## Purpose

This specification defines the **role→model policy** that decides which model every kind of
agent runs on, how agents record their model intent (follow the policy vs. an explicit pin),
and how policy changes propagate to the fleet. It replaces the v1 tier system
(economy/standard/premium), which was removed entirely in 0.2.0 — the rank values survive only
as a private internal seed table, never as accepted user input.

## Scope

This specification covers:

- The agent roles the policy knows about and their built-in model classes
- The user registry overlay (`~/.openclaw/docket-models.json`)
- Model intent per agent (`modelSource: policy | pinned`) and migration inference
- Viewing/changing the policy (`docket models`) and pinning agents (`docket profile`)
- Automatic re-resolution of policy-following agents on policy changes
- Removed tier names and the private internal rank-anchor seed table; the one-shot legacy
  `profiles:` registry migration
- The pricing table used for cost estimation

This specification does NOT cover cost accumulation or budget caps (see cost-tracking.spec.md).

## Requirements

### Roles and built-in policy

1. The policy **MUST** know exactly eight roles: the six specialist roles
   (`manager`, `programmer`, `reviewer`, `tester`, `knowledge`, `security`) plus the two
   project-agent types (`repo`, `task`), which double as project agents' policy roles.
2. Each role **MUST** belong to one of two built-in classes, chosen for token efficiency:
   - **cheap** (high-volume, low reasoning density): `manager`, `reviewer`, `tester`,
     `knowledge`, `task` → the economy rank anchor (default `anthropic/claude-haiku-4-5`)
   - **strong** (reasoning-dense): `programmer`, `security`, `repo` → the standard rank
     anchor (default `anthropic/claude-sonnet-4-6`)
3. Stronger models (opus-class) **MUST NOT** be a standing role default; they are reachable
   only as a per-agent pin.
4. Each role **MUST** carry a short human-readable WHY string shown by `docket models`.
5. Resolving an unknown role **MUST** fall back to `DEFAULT_MODEL` (no error).

### User registry overlay

1. `~/.openclaw/docket-models.json` **MAY** contain a `roles` map (`role → provider/model`);
   well-formed entries **MUST** override the built-in role defaults. Unknown role names
   **MUST** be ignored with a warning.
2. A legacy registry containing only a `profiles` map **MUST** keep working: the rank
   anchors are overridden first, then role defaults re-derive from them, then any `roles`
   entries overlay on top.
3. A corrupt registry **MUST** warn on stderr and keep built-in defaults (no crash).

### Model intent per agent

1. Every agent **MUST** record `modelSource` in `.docket-meta.json`: `policy` (follow the
   role policy) or `pinned` (explicit model choice).
2. Agents created without an explicit model, or with a model equal to their role's policy
   model, **MUST** be stamped `policy`; an explicit divergent model **MUST** be stamped
   `pinned`.
3. Agents predating this field **MUST** have it inferred on read: model equals the role's
   policy model → `policy`, otherwise → `pinned` (so a pre-existing agent is never silently
   moved to a different model). `docket doctor` **MUST** backfill the field persistently.

### Changing the policy (docket models)

1. `docket models` **MUST** list ROLE, MODEL, PRICE, SOURCE (builtin/user), and WHY for all
   eight roles, plus the default model and the fallback chain.
2. `docket models set <role> <provider/model>` **MUST** validate the model, persist the
   override to the registry, and apply it live.
3. `docket models preset <name>` **MUST** map the preset's cheap/strong classes onto all
   eight roles and persist them, plus the rank anchors and default.
4. After any policy change (set/preset/reset), every **policy-following** agent (specialist
   and project, registered or not) **MUST** be re-resolved to its role's new model in both
   config sources, with one gateway restart at the end and an audit entry per change.
   Pinned agents **MUST NOT** be touched.

### Pinning agents (docket profile)

1. `docket profile <id> <provider/model>` **MUST** pin the agent: set the model in both
   config sources and `modelSource: pinned`, then restart the gateway.
2. `docket profile <id> default` **MUST** re-attach the agent to its role policy: resolve the
   role's model, set it, and stamp `modelSource: policy`.
3. `docket profile <id>` with no argument **MUST** display the current model, role (with WHY),
   source (policy/pinned), and budget.
4. `docket profile` **MUST** work for specialists as well as project agents.

### Tier names (removed, 0.2.0)

1. The tier names `economy`, `standard`, `premium` **MUST NOT** be accepted anywhere a model
   or role value is expected — `docket profile <id> premium` and `docket models set premium
   <model>` both **MUST** fail with an error naming a full `provider/model` id, not resolve.
   Removed in 0.2.0 per the D-2 deprecation-window exit; see ROADMAP.md D-2.
2. The three rank values survive **only** as a private internal seed table
   (`_RANK_ANCHORS` in `core/models_policy.py`) used to (a) pick each role's default model —
   `economy` seeds the cheap-class roles, `standard` seeds the strong-class roles — and
   (b) reconstruct per-role overrides when migrating a legacy `profiles:` registry key (see
   Legacy registry migration below). This table is **not** surfaced by any command and is not
   a live runtime fallback chain.

### Legacy registry migration

1. On first load of a user's `~/.openclaw/docket-models.json`, if it has a `profiles:` key
   but no `roles:` key, docket **MUST** derive equivalent per-role overrides from the
   `profiles:` tier-anchor values (using the same cheap/strong-class mapping as the built-in
   seed) and write them under `roles:`, then remove `profiles:`. This migration **MUST** run
   at most once — a no-op on every subsequent load.
2. If a registry already has both `profiles:` and `roles:`, the migration **MUST NOT** touch
   `profiles:` (it is left as a residual key rather than silently discarded).
3. `docket doctor` **SHOULD** flag a residual `profiles:` key found under the condition in
   (2) as an advisory, non-blocking finding.

### Pricing

1. Each built-in model **MUST** have a pricing entry in USD per million tokens, expressed
   as `input:output:cacheWrite:cacheRead`.
2. A model without pricing **MUST** report `n/a` (never $0.00) in cost output.

## Interface Contracts

### CLI Command Signatures

```bash
docket models                              # Show the role→model policy
docket models set <role|default> <provider/model>
docket models preset [anthropic|openai|google|openrouter-free|openrouter]
docket models reset                        # Restore built-in defaults
docket profile <agent-id>                  # Show model, role, source, budget
docket profile <agent-id> <provider/model> # Pin
docket profile <agent-id> default          # Follow the role policy
docket profile <agent-id> --budget <USD>   # Spend cap (see cost-tracking)
```

### Built-in policy (Anthropic defaults)

| Role | Class | Model | Why |
| ---- | ----- | ----- | --- |
| manager | cheap | claude-haiku-4-5 | high-volume coordination, shallow reasoning |
| reviewer | cheap | claude-haiku-4-5 | triage and review, low reasoning density |
| tester | cheap | claude-haiku-4-5 | run tests and report |
| knowledge | cheap | claude-haiku-4-5 | retrieval and summarization |
| task | cheap | claude-haiku-4-5 | project default for task agents |
| programmer | strong | claude-sonnet-4-6 | code generation |
| security | strong | claude-sonnet-4-6 | audit depth |
| repo | strong | claude-sonnet-4-6 | project default for repo agents |

### Pricing Table (USD per MTok, Anthropic defaults)

| Anchor | Model | Input | Output |
| ------ | ----- | ----- | ------ |
| economy | claude-haiku-4-5 | 0.80 | 4.00 |
| standard | claude-sonnet-4-6 | 3.00 | 15.00 |
| premium | claude-opus-4-6 | 15.00 | 75.00 |

### Registry file shape (current)

```json
{
  "default": "anthropic/claude-sonnet-4-6",
  "roles":    { "programmer": "openai/gpt-4.1" },
  "pricing":  { "openai/gpt-4.1": {"input": 2.00, "output": 8.00} }
}
```

### Registry file shape (legacy, pre-migration — auto-converted on load)

```json
{
  "default": "anthropic/claude-sonnet-4-6",
  "profiles": { "economy": "openai/gpt-4.1-nano" }
}
```

Loading the file above migrates it once to `{"default": "...", "roles": {"knowledge": "openai/gpt-4.1-nano", "task": "openai/gpt-4.1-nano", ...}}` (the `economy` value fanned out to the cheap-class roles) and drops `profiles:`.

### Return Codes

Like the workflow command (see workflow-integration.spec.md), `docket profile` and `docket
models` use a plain success/failure contract — `0` on success, `1` on any error (agent not
found, invalid model, unknown role). There is no distinct exit code per error kind.

## Examples

### Viewing and changing the policy

```bash
$ docket models
  ROLE          MODEL                        PRICE          SOURCE    WHY
  manager       anthropic/claude-haiku-4-5   $0.80/$4.00    builtin   high-volume coordination...
  programmer    anthropic/claude-sonnet-4-6  $3.00/$15.00   builtin   code generation
  ...

$ docket models set programmer openai/gpt-4.1
✓ programmer → openai/gpt-4.1
→ Re-resolving policy-following agents...
  programmer (programmer): anthropic/claude-sonnet-4-6 → openai/gpt-4.1
```

### Pinning and unpinning an agent

```bash
$ docket profile mywebsite anthropic/claude-opus-4-6
✓ Model pinned: anthropic/claude-sonnet-4-6 → anthropic/claude-opus-4-6

$ docket profile mywebsite default
✓ Model: anthropic/claude-opus-4-6 → anthropic/claude-sonnet-4-6 (follows role policy 'repo')
```

## Validation

### Pre-conditions

- The target agent **MUST** exist (profile) / the role **MUST** be known (models set).

### Post-conditions

- After a pin or policy change, `.docket-meta.json` `model` **MUST** equal the agent's model
  in `openclaw.json` `agents.list`, `modelSource` **MUST** reflect the intent, and the
  gateway **MUST** have been restarted exactly once per command.

### Invariants

- A role **MUST** always resolve to exactly one model id.
- A pinned agent's model **MUST** survive any number of policy/preset changes.
- Pricing **MUST** exist for every built-in policy model.

## Changelog

### Version 2.1.0 (2026-07-02)

- CH-10 spec truth pass (following CH-6's tier-shim removal, D-2 exit): tier names are no
  longer "deprecated aliases" — they are rejected outright with an error. Rewrote the section
  to describe the rank anchors as a private, non-user-facing internal seed table with no
  CLI-layer presence, not a resolved/warned user input path. Added the Legacy registry
  migration requirements and a matching example (the one-shot `profiles:` → `roles:`
  conversion CH-6 shipped). Fixed the Return Codes section to the real plain `0`/`1` contract.

### Version 2.0.0 (2026-06-12)

- Replaced the three-tier profile system with the role→model policy (Phase 6b, MA-9…MA-11)
- Added `modelSource` intent, auto re-resolution of policy followers, specialist coverage
- Tier names demoted to deprecated aliases over the fallback rank anchors

### Version 1.0.0 (2026-06-09)

- Initial model-profiles specification
- Defined the three tiers, their models, and the pricing table
