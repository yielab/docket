# Model Policy Specification

**Version**: 2.5.1
**Status**: Complete
**Last Updated**: 2026-08-04

## Purpose

This specification defines the **role→model policy** that decides which model every kind of
agent runs on, how agents record their model intent (follow the policy vs. an explicit pin),
and how policy changes propagate to the fleet. It replaces the v1 tier system
(economy/standard/premium), which was removed entirely in 0.2.0 — the rank values survive only
as a private internal seed table, never as accepted user input.

## Scope

This specification covers:

- The agent roles the policy knows about and their built-in model classes
- The user registry overlay (`~/.docket/docket-models.json`), including the registry-
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

It also does not evaluate whether a LiteLLM-class sidecar gateway can front the daemon's
provider config as a central-keys/metering layer (ROADMAP Phase 18 L-5, decision D-18) — that
was investigated as a spike, separately from any behavior this spec defines. **L-5 spike
concluded 2026-07-30: yes, the daemon tolerates the base-url swap cleanly, and no new code was
required** — the `docket models provider` command documented below (Presets, Examples) already
is that mechanism; it was simply never exercised against a non-local base URL before. See
"L-5 spike findings" below for the full dated evidence trail. **Superseded by ROADMAP Phase 19
P19-7b (2026-08-03): the daemon and the ACL (`edges/adapters/openclaw.py`) this spike
investigated are both deleted outright.** The spike's question ("does the daemon tolerate a
base-url swap") no longer has a subject — `docket models provider add` now writes the same
provider block into `core/fleet.py`'s `fleet.json` `providers` dict (`core/provider.py`'s
`add_local_provider`/`get_local_provider`), read directly by `edges/adapters/llm.py`'s
`resolve_endpoint` to build `DocketDriver`'s own chat client. There is no daemon in the loop
to "tolerate" anything, so a base-url swap is trivially docket's own, first-party behavior now,
not a question of upstream compatibility. The evidence trail below is kept verbatim as the
historical record of the investigation that originally validated the mechanism's shape; read
every "the daemon" reference in it as describing a system this codebase no longer ships.

## L-5 spike findings (investigated 2026-07-30, verdict: yes — no code shipped, none was needed; historical — superseded by P19-7b, see note above)

1. **Question.** ROADMAP Phase 18 L-5 / decision D-18 asks whether OpenClaw's daemon tolerates
   pointing its provider config at a LiteLLM-class sidecar gateway cleanly enough to justify
   wrapping one — an *opt-in* pattern for central API-key custody (ending per-agent plaintext-
   `.env` fan-out), per-call cost metering at the root, failover, and caching. The hard
   constraint regardless of the answer: hand-rolled per-vendor model clients are permanently
   banned (D-18) — any implementation must go through the daemon's own provider config via the
   ACL, never a new SDK dependency.

2. **The mechanism already ships in docket, unrelated to this spike.** `docket models provider
   add <name> <base-url> [--model ID] [--name NAME] [--ctx N] [--max-tokens N]`
   (`cli/_provider.py` → `core/provider.py` → `edges/adapters/openclaw.py`'s
   `add_local_provider`/`local_provider_config`, tested in `tests/python/test_provider_registration.py`
   since M5) already writes an arbitrary `models.providers.<name>` block — `{baseUrl, apiKey,
   api: "openai-completions", models: [...]}` — into `openclaw.json` for **any** base URL, not
   only a literal local llama.cpp/LM Studio server. The command's naming and messaging are
   oriented around the "local free model" use case (`DEFAULT_PROVIDER = "local"`, UI text
   referencing "llama.cpp/LM Studio"), but nothing in the mechanism itself is local-only: it is
   a generic OpenAI-compatible-endpoint registration, and a LiteLLM proxy server (which itself
   implements the OpenAI ChatCompletions API) is indistinguishable from that shape as far as
   this code path is concerned.

3. **Confirmed live against this project's actual production daemon, not just in theory.**
   `openclaw --version` on this host reports `2026.2.23` — the same version cited throughout
   the ACL, `core/runtime_driver.py`, `core/models_policy.py`, and the L-4 spike. Reading
   (never writing) the real `~/.openclaw/openclaw.json` confirmed `models.providers` already
   contains two custom entries beyond any built-in vendor, both matching
   `local_provider_config`'s exact schema (`baseUrl`/`apiKey`/`api: "openai-completions"`/
   `models[]`): one pointed at a loopback local inference server, one pointed at a remote
   OpenAI-compatible gateway host reached over HTTPS. Reading `agents.list` in the same file
   confirmed several already-registered fleet agents have their `model` field set to
   `<custom-provider-name>/<model-id>` — this exact base-url-swap mechanism is not merely
   configured but is presently the live routing path for real agent turns on this fleet's
   actual daemon, today. No file under `~/.openclaw` was written, renamed, or deleted for this
   spike — both reads used plain read-mode file access, the same class of operation
   `edges/store.py`'s own read path performs routinely.

4. **Confirmed as an intentional, documented upstream mechanism, not an accidental side
   effect.** docs.openclaw.ai's `concepts/model-providers` and `gateway/config-tools` pages
   (fetched 2026-07-30) state directly: "Use `models.providers` (or `models.json`) to add
   custom providers or OpenAI/Anthropic-compatible proxies," and list self-hosted local
   proxies — naming LM Studio, vLLM, and **LiteLLM by name** — as example backends for exactly
   this field. The `baseUrl`/`apiKey`/`api` (`"openai-completions"` for self-hosted
   `/v1/chat/completions` backends)/`models` shape matches `core/provider.py`'s
   `local_provider_config` field-for-field. One documented caveat: "Configuring a custom/local
   provider `baseUrl` is also the narrow network trust decision for model HTTP requests:
   OpenClaw allows that exact `scheme://host:port` origin through the guarded fetch path" — a
   per-origin allowlist gate, not a blocker (the two origins already live on this fleet's
   daemon are already past that gate, and a same-host sidecar on `127.0.0.1` is the same
   locality class as the existing `local` entry).

5. **Cross-checked against upstream commit history** (`gh api search/commits`,
   `repo:openclaw/openclaw`): the baseUrl/api inheritance behavior behind this mechanism
   predates this fleet's daemon (`fix(models): inherit baseUrl and api from provider config`,
   `6bf2f0e`, 2026-01-27, before the `2026.2.23` version this project targets); a later
   hardening commit (`fix(agents): scope custom provider baseUrl SSRF trust by origin`,
   `4484000`, 2026-05-15) postdates `2026.2.23`, so the exact trust-boundary implementation on
   this fleet's daemon may be an earlier revision of that guard than current docs describe —
   noted as a caveat, not a contradiction: the core baseUrl-swap capability itself is confirmed
   present and in active use well before that hardening commit. Current stable per
   `gh release list --repo openclaw/openclaw`: `2026.7.1` (2026-07-13), matching the version
   the L-4 spike probed.

6. **What a wrapped-gateway deployment looks like, with zero new docket code.** Stand up a
   LiteLLM (or equivalent) proxy that holds the real per-vendor keys and exposes an
   OpenAI-compatible `/v1` endpoint; `docket models provider add gateway
   http://127.0.0.1:<port>/v1 --model <model-id>` registers it exactly like the custom
   providers already live on this fleet; `docket models set <role> gateway/<model-id>` (or
   `docket profile <id> gateway/<model-id>`) points a role or agent at it, through the same
   code path every other model swap already uses. A second model behind the same sidecar
   registers under a second provider name pointed at the identical `baseUrl` — `providers` is
   keyed by name, not by origin, and `add_local_provider` replaces one name's whole block
   rather than merging into its `models` list — a naming quirk, not a functional blocker, and
   already how this fleet's own two custom entries coexist today. All traffic still flows
   through the daemon's own HTTP client; docket writes only JSON config through the ACL. No new
   SDK, no per-vendor client code — satisfies D-18's permanent ban.

7. **What the swap does not get you for free.** `core/runtime_driver.py`'s
   `DriverCapabilities` already documents that this daemon version reports token counts only,
   never a USD cost field (`reports_cost_usd=False`) — that is unrelated to which `baseUrl` a
   provider points at, so a sidecar's own per-call USD ledger would not automatically surface
   inside docket's `usage()`/`docket cost` pipeline; reading it would need a separate, explicit
   integration against the sidecar's own admin/spend API (a distinct future card, not answered
   by this spike). Failover and caching are likewise entirely the sidecar's own configuration,
   orthogonal to whether the daemon tolerates the swap. Metering therefore stays exactly where
   ROADMAP already parks it absent that follow-up: L-1's `usage()` plus R-5's estimates (see
   cost-tracking.spec.md).

8. **Verdict: yes, cleanly — and no code ships from this spike.** The daemon (confirmed
   `2026.2.23`, this fleet's real target) already tolerates an arbitrary base-url swap for an
   OpenAI-compatible provider as a first-class, upstream-documented mechanism (LiteLLM named
   explicitly), and it is already live, in production, carrying real agent traffic on this
   exact fleet today. Docket already ships the ACL-safe plumbing to drive it (`docket models
   provider add`, pre-existing since M5, ACL-clean, SDK-free). There is nothing new to build to
   satisfy the literal ask, so per this card's own bar ("ship code only if… the implementation
   is genuinely small"), the correctly-sized deliverable is zero lines of new code plus this
   evidence record — a second, redundant "wrap a gateway" command over the same JSON write
   would be speculative surface, not a genuine gap.

9. **What would change this answer.** If a real need arises for one provider name to expose
   several models without the per-model provider-name workaround in finding 6,
   `core/provider.py`'s `register_local_provider`/`local_provider_config` and
   `edges/adapters/openclaw.py`'s `add_local_provider` would need a small, well-scoped
   extension: accept a list of model specs and merge additively into an existing
   `models.providers.<name>.models` array instead of overwriting the whole block. Not built
   here, per this card's "do not build a speculative feature" instruction — a real follow-up
   only if that friction is actually hit.

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

1. `~/.docket/docket-models.json` **MAY** contain a `roles` map (`role → provider/model`);
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
   and project, registered or not) **MUST** be re-resolved to its role's new model in
   `.docket-meta.json` — the only place a model lives (ROADMAP Phase 19 P19-6: `fleet.json`
   tracks bare registration only, never a copy of `model`, so there is no second config source
   to keep in sync, and no gateway to restart since P19-7b deleted it). Pinned agents **MUST
   NOT** be touched.
5. Each policy change (`set`/`preset`/`reset`) **MUST** write one audit-log entry (the
   `models.*` action family — see audit.spec.md's Requirement 1) recording the role(s) affected
   (or `default`) and the before/after model, so the audit log alone answers "which role
   changed, from what, to what, and when" without consulting this registry file. A
   `preset`/`reset` call, which can touch every role at once, **MUST** be recorded as one entry
   listing every role's before/after pair, not one entry per role (ROADMAP Phase 15 G-4b).

### Pinning agents (docket profile)

1. `docket profile <id> <provider/model>` **MUST** pin the agent: set the model in
   `.docket-meta.json` (the only place it lives, see "Changing the policy" above) and
   `modelSource: pinned`. There is no gateway-restart step: `restart_gateway()` and its ~15
   ceremonial call sites across `cli/` were deleted outright (CL-C, ROADMAP Phase 19 wave 14) —
   not kept as a no-op stub — since nothing ever observed its return value.
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

1. On first load of a user's `~/.docket/docket-models.json`, if it has a `profiles:` key
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
display and comparative estimates only — recorded spend comes from measured token counts in
docket's own per-session storage (ROADMAP Phase 19 P19-4/P19-7b; `_cfg.SESSIONS_DIR`, see
cost-tracking.spec.md), not a daemon. Resolved gap (Phase 18 L-2): the table now carries a `local/
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

- After a pin or policy change, `.docket-meta.json` `model` **MUST** reflect the new value —
  the only place a model lives (ROADMAP Phase 19 P19-6: `fleet.json`'s `FleetAgent` tracks bare
  registration only, never a copy of `model`, so there is no second location to keep in sync).
  `modelSource` **MUST** reflect the intent (`policy` vs `pinned`).

### Invariants

- A role **MUST** always resolve to exactly one model id.
- A pinned agent's model **MUST** survive any number of policy/preset changes.
- Pricing **MUST** exist for every built-in policy model.

## Changelog

### Version 2.5.1 (2026-08-04)

- **CL-C (ROADMAP Phase 19, wave 14 dead-code sweep).** `restart_gateway()`/`RestartResult` and
  every call site that ceremonially invoked them after a mutating command (including `docket
  profile`'s) are deleted outright, not kept as a no-op stub — unlike `gateway_active()` (kept;
  still backs the `gateway` field in `docket snapshot` and the `serve` read API), nothing
  external ever observed `restart_gateway`'s return value. Corrected the "Pinning agents"
  requirement, which still described it as "still runs... but is now a no-op."

### Version 2.5.0 (2026-08-03)

- **ROADMAP Phase 19 P19-7b — the OpenClaw daemon and the ACL are deleted.** Superseded the
  L-5 spike's live subject: `docket models provider add` now writes its provider block into
  `core/fleet.py`'s `fleet.json` `providers` dict (`core/provider.py`'s
  `add_local_provider`/`get_local_provider`), read directly by `edges/adapters/llm.py`'s
  `resolve_endpoint` — there is no daemon provider config or ACL in the loop any more, so a
  base-url swap is docket's own first-party behavior, not a question of upstream tolerance.
  The L-5 evidence trail is kept verbatim as historical record; added a note at the top of the
  Purpose section and a header annotation on "L-5 spike findings" marking it historical. Fixed
  three path references (`~/.openclaw/docket-models.json` -> `~/.docket/docket-models.json`,
  ROADMAP P19-6/P19-7b moved `MODEL_REGISTRY_FILE` under `DOCKET_HOME`). Corrected the pricing
  section's "recorded spend comes from the daemon" to point at docket's own per-session storage
  (`_cfg.SESSIONS_DIR`). Corrected the profile/policy-change post-condition: it no longer
  describes keeping `.docket-meta.json`'s model in sync with `openclaw.json`'s `agents.list`
  (deleted; and per P19-6, `fleet.json` never tracked model in the first place, so there was
  already only one place it lived). Also fixed "Changing the policy"/"Pinning agents"
  requirements 4/1, which still said "both config sources, with one gateway restart" — there is
  one config source (`.docket-meta.json`) and `restart_gateway()` is now an honest
  `status="no_daemon"` no-op kept only for call-site compatibility.

### Version 2.4.0 (2026-07-30)

- ROADMAP Phase 18 L-5 spike (decision D-18) concluded, docs-only: does the OpenClaw daemon
  tolerate a base-url swap cleanly enough for a LiteLLM-class sidecar gateway? **Verdict: yes**,
  confirmed against this project's live production daemon (`openclaw 2026.2.23`) and upstream
  docs/commit history — and the mechanism is `docket models provider add`, already shipped since
  M5, so **no code was written**. See the new "L-5 spike findings" section (placed after Scope)
  for the full dated evidence trail, including what the swap does and does not get you for free
  and the one narrow follow-up (multi-model-per-provider-name) that would justify future code.

### Version 2.3.3 (2026-07-30)

- ROADMAP Phase 15 G-4b (audit coverage for `models.*`): split the old Requirement 4 (which had
  started conflating live re-resolution with audit recording, and claimed the latter before it
  was actually shipped) into a re-resolution requirement (4, unchanged in substance) and a new
  Requirement 5 naming the `models.*` audit family precisely: one entry per `set` naming the
  role/`default` touched and its before/after model, one entry per `preset`/`reset` naming every
  role's before/after pair rather than one entry per role. See audit.spec.md Version 2.2.0 for
  the entry shape and shipped implementation.

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
