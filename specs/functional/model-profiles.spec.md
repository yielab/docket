# Model Policy Specification

**Version**: 2.3.2
**Status**: Complete
**Last Updated**: 2026-07-30

## Purpose

This specification defines the **role→model policy** that decides which model every kind of
agent runs on, how agents record their model intent (follow the policy vs. an explicit pin),
and how policy changes propagate to the fleet. It replaces the v1 tier system
(economy/standard/premium), which was removed entirely in 0.2.0 — the rank values survive only
as a private internal seed table, never as accepted user input.

## Scope

This specification covers:

- The agent roles the policy knows about and their built-in model classes
- The user registry overlay (`~/.openclaw/docket-models.json`), including the registry-
  overridable rank-anchor seed table (`rankAnchors`)
- Model intent per agent (`modelSource: policy | pinned`) and migration inference
- Viewing/changing the policy (`docket models`) and pinning agents (`docket profile`)
- Automatic re-resolution of policy-following agents on policy changes
- The built-in provider presets (`docket models preset`), including the free/local path
- Removed tier names and the private internal rank-anchor seed table; the one-shot legacy
  `profiles:` registry migration
- The pricing table used for cost estimation, including local-provider and marketplace-
  provider (OpenRouter) pricing honesty

This specification does NOT cover cost accumulation or budget caps (see cost-tracking.spec.md),
nor the declarative role-archetype registry itself (`name`/`scope`/`gateContract`/…, ROADMAP
Phase 16 W-6) — see role-archetypes.spec.md. This spec covers only the one integration point
between the two: how a role with no named row in this policy's table resolves via its
archetype's `modelClass` instead (see "Roles and built-in policy", requirement 5).

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
5. Resolving a role not in this table **MUST NOT** always collapse straight to `DEFAULT_MODEL`:
   if the role is a registered pod archetype (ROADMAP Phase 16 W-6; e.g. a starter-library role
   like `researcher`) whose `modelClass` this table has no named row for, it **MUST** resolve
   via that `modelClass` against the live rank anchors instead (`economy` for `cheap`,
   `standard` for `strong`) — see role-archetypes.spec.md. Only a role that is neither a named
   entry here nor a registered archetype **MUST** fall back to `DEFAULT_MODEL` (no error, either
   way).

### User registry overlay

1. `~/.openclaw/docket-models.json` **MAY** contain a `roles` map (`role → provider/model`);
   well-formed entries **MUST** override the built-in role defaults. Unknown role names
   **MUST** be ignored with a warning.
2. A legacy registry containing only a `profiles` map **MUST** keep working: the rank
   anchors are overridden first, then role defaults re-derive from them, then any `roles`
   entries overlay on top.
3. A corrupt registry **MUST** warn on stderr and keep built-in defaults (no crash).
4. The registry **MAY** contain a `rankAnchors` map (`{"economy"|"standard"|"premium":
   "provider/model"}`) that overrides the private rank-anchor seed table (see Tier names
   below) *before* role defaults are derived from it (Phase 18 L-2). This is how a fleet on
   a non-Anthropic preset stops showing Claude ids in the anchor value `docket models`
   displays. Unknown anchor names or malformed model ids **MUST** be ignored (same tolerance
   as `roles`/`default`).

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
   eight roles, plus the default model and the rank anchors (labeled "rank anchors", not
   "fallback" — see Tier names below for why that label was corrected).
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
2. The three rank values survive as a private internal seed table (`_RANK_ANCHORS` in
   `core/models_policy.py`, defaulting to Anthropic ids) used to (a) pick each role's default
   model — `economy` seeds the cheap-class roles, `standard` seeds the strong-class roles —
   and (b) reconstruct per-role overrides when migrating a legacy `profiles:` registry key
   (see Legacy registry migration below). "Private" means **not accepted as a CLI argument
   under the tier names** — `docket models set economy <model>` still fails per rule 1 above.
   It is, however, **registry-overridable** (see User registry overlay's `rankAnchors`, Phase
   18 L-2) and **is displayed** (read-only) by `docket models`, labeled "rank anchors" — a
   correction from the prior "fallback" label, which was a false claim: nothing in docket
   degrades a request to a cheaper model on failure. It is a role-default seed table, not a
   live runtime fallback chain, and the display now says so.
3. **Scope note:** the eval harness's `docket eval --tier <economy|standard|premium>` flag
   (eval.spec.md) is a live-eval matrix selector for spot-checks, not a model value or role
   key — it is the one deliberately surviving user-facing use of the tier words and does not
   contradict rule 1 (which governs model/role value positions only).

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

### Presets (docket models preset)

1. The built-in presets **MUST** include `anthropic` (default), `openai`, `google`,
   `openrouter-free`, `openrouter`, and `local`.
2. The `local` preset **MUST** require no API key (a local OpenAI-compatible endpoint —
   llama.cpp/LM Studio/vLLM/Ollama — registered separately via `docket models provider`) and
   **MUST** price its models at `$0 (local)`.
3. Applying a preset **MUST** persist the preset's own economy/standard/premium values as the
   registry's `rankAnchors` (see User registry overlay), not just the per-role overrides — so
   the anchor value `docket models` displays never lags behind the fleet's actual preset after
   a non-Anthropic preset is applied.

### Pricing

1. Each built-in model **MUST** have a pricing entry in USD per million tokens, expressed
   as `input:output:cacheWrite:cacheRead`.
2. A model without pricing **MUST** report `n/a` (never $0.00) in cost output.
3. A model whose provider prefix is a recognized local provider (`local`, `ollama`,
   `lmstudio`) **MUST** report `$0 (local)` — this is the true cost, not a placeholder for
   missing data, and **MUST NOT** fall through to the generic `n/a` path.
4. A model routed through a marketplace provider whose per-model pricing docket does not
   track (`openrouter`, unless the specific model id is one of the curated
   `openrouter-free` rows priced at `$0.00`) **MUST** report a distinct, informative label
   (`n/a (bring your own)`) rather than the plain `n/a` used for an ordinary uncatalogued
   model — docket does not invent a number for pricing that changes per model/account.

## Interface Contracts

### CLI Command Signatures

```bash
docket models                              # Show the role→model policy
docket models set <role|default> <provider/model>
docket models preset [anthropic|openai|google|openrouter-free|openrouter|local]
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
| programmer | strong | claude-sonnet-4-6 | code generation |
| security | strong | claude-sonnet-4-6 | audit depth |
| repo | strong | claude-sonnet-4-6 | project default for project agents |

The role set above is `ALL_ROLES` (`core/models_policy.py`) — there is **no** `task` role
(it left with the repo/task dual-type model). `portfolio-manager` is additionally accepted by
`docket models set` (it is in `ROLE_CLASS`, cheap) but is not displayed in the `docket models`
table unless set — a known display quirk.

### Pricing Table (USD per MTok, Anthropic defaults)

| Class | Model | Input | Output |
| ----- | ----- | ----- | ------ |
| cheap | claude-haiku-4-5 | 0.80 | 4.00 |
| strong | claude-sonnet-4-6 | 3.00 | 15.00 |
| (premium anchor) | claude-opus-4-6 | 15.00 | 75.00 |

Pricing is a manual snapshot (`MODEL_PRICING`, dated by `MODEL_PRICING_AS_OF`) used for
display and comparative estimates only — recorded spend comes from the daemon
(cost-tracking.spec.md). Resolved gap (Phase 18 L-2): the table now carries a `local/
qwen3-30b-a3b` row and the three `openrouter-free` preset models, all priced at zero
(sourced from docket's own free-tier/local claims, not an invented figure); `LOCAL_PROVIDERS`
(`local`, `ollama`, `lmstudio`) independently price at `$0 (local)` regardless of whether the
specific model id is catalogued. The `openrouter` (paid) preset's two non-free-tier models
are deliberately left uncatalogued — OpenRouter re-prices per underlying model and account
tier and docket will not hardcode a number it cannot keep current — and report `n/a (bring
your own)` instead.

### Registry file shape (current)

```json
{
  "default": "anthropic/claude-sonnet-4-6",
  "roles":       { "programmer": "openai/gpt-4.1" },
  "rankAnchors": { "standard": "openai/gpt-4.1-mini" },
  "pricing":     { "openai/gpt-4.1": {"input": 2.00, "output": 8.00} }
}
```

### Registry file shape (legacy, pre-migration — auto-converted on load)

```json
{
  "default": "anthropic/claude-sonnet-4-6",
  "profiles": { "economy": "openai/gpt-4.1-nano" }
}
```

Loading the file above migrates it once to `{"default": "...", "roles": {"manager": "openai/gpt-4.1-nano", "reviewer": "openai/gpt-4.1-nano", "tester": "openai/gpt-4.1-nano", "knowledge": "openai/gpt-4.1-nano"}}` (the `economy` value fanned out to the cheap-class roles — there is no `task` role; see Built-in policy above) and drops `profiles:`.

### Return Codes

Like every other docket command (see cli-interface.spec.md), `docket profile` and `docket
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

### Switching the whole fleet to a free/local preset

```bash
$ docket models preset local
✓ Preset 'local' applied.
  No API key needed. Verify your local runtime is up, then register the endpoint:
  docket models provider [name] [base_url]   # ping + register

$ docket models
  ROLE          MODEL                    PRICE        SOURCE    WHY
  manager       local/qwen3-30b-a3b      $0 (local)   user      high-volume coordination...
  programmer    local/qwen3-30b-a3b      $0 (local)   user      code generation
  ...
  default       local/qwen3-30b-a3b
  rank anchors  local/qwen3-30b-a3b → local/qwen3-30b-a3b → local/qwen3-30b-a3b
  (role-default seed table — not a runtime fallback chain; overridable in docket-models.json)
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

### Version 2.3.2 (2026-07-30)

- Retargeted the Return Codes cross-reference away from workflow-integration.spec.md — `docket
  workflow` (the Lobster surface it named) was retired per ROADMAP D-16 (Phase 16 W-3) and that
  spec file was deleted.

### Version 2.3.1 (2026-07-30)

- ROADMAP Phase 16 W-6 (declarative role archetypes): `resolve_role_model` now falls back to a
  role's own archetype `modelClass` (against the live rank anchors) before giving up on
  `DEFAULT_MODEL`, for any role that is a registered pod archetype but has no named row in this
  policy's table (e.g. `researcher`). The four legacy pod roles (lead/implementer/reviewer/
  tester) are unaffected — they still resolve through their existing named
  `manager`/`programmer`/`reviewer`/`tester` rows exactly as before. No new hardcoded role name
  was added to `ALL_ROLES`/`ROLE_CLASS` — see role-archetypes.spec.md for the archetype
  registry this integrates with.

### Version 2.3.0 (2026-07-30)

- Phase 18 L-2 (finish provider agnosticism) — closed the gaps 2.2.0 identified but left open:
  - The rank-anchor seed table is now **registry-overridable** via a `rankAnchors` map (User
    registry overlay); `docket models preset` persists its own economy/standard/premium as
    `rankAnchors` too, so a non-Anthropic preset leaves no Claude residue anywhere in the
    display.
  - The anchor display line is relabeled "rank anchors" (was "fallback" — a false claim;
    nothing in docket degrades a request to a cheaper model on failure).
  - Added the `local` preset (Presets section) — no API key, prices at `$0 (local)`.
  - Closed the pricing gap: `local`/`ollama`/`lmstudio` provider prefixes always price at `$0
    (local)`; the `openrouter-free` preset's three curated models are priced at `$0.00` (a
    restatement of docket's own pre-existing free-tier claim, not an invented figure); any
    other OpenRouter route reports `n/a (bring your own)` instead of a stale/fabricated
    number.
  - Fixed the stale `docket models set task <model>` and raw `openclaw models status`
    guidance strings in `cli/_provider.py` (`task` is not a role; the second string violated
    "no direct OpenClaw CLI") — both now name real, existing `docket` commands.
  - Fixed a stale example in this spec's own Legacy registry migration section that still
    listed a `task` role in the migrated output.
  - `docket auth login/key/setup` now accept `--provider <name>` (default: `anthropic`),
    threaded through the ACL's `auth_setup_token`/`auth_paste_token` instead of a hardcoded
    provider string (documented in cli-interface.spec.md, not this file — auth profiles are
    out of this spec's scope).

### Version 2.2.0 (2026-07-30)

- Truth pass (Platformization baseline): removed the phantom `task` role from the built-in
  policy table (`ALL_ROLES` has no such role — this row was the source of the broken
  `docket models set task` guidance in `cli/_provider.py`); noted the settable-but-hidden
  `portfolio-manager` role; re-keyed the pricing table by class instead of the removed tier
  vocabulary and named the missing-OpenRouter/local-rows gap (Phase 18 L-2); scoped the
  tier-removal rule against `docket eval --tier` (a live-eval matrix selector, not a model
  value) so the two specs no longer contradict each other.

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
