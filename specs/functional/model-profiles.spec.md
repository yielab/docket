# Model Policy Specification

**Version**: 3.2.1
**Status**: Complete. **P30-3** (ADR 0012 §2 rule 6) adds a per-pipeline-step model override,
above the policy, resolved once per hop and never persisted — see "Model intent per
agent" requirement 4.
**Last Updated**: 2026-10-08

## Purpose

This specification defines the **role→model policy** that decides which model every kind of
agent runs on, and how policy changes propagate to the fleet. A model comes from exactly three
layers: the role policy, a pod's own role overlay, and a pipeline step's `model:`. It replaces the v1 tier system
(economy/standard/premium), which was removed entirely in 0.2.0 — the rank values survive only
as a private internal seed table, never as accepted user input.

## Scope

This specification covers:

- The agent roles the policy knows about and their built-in model classes
- The user registry overlay (`~/.docket/docket-models.json`), including the registry-
  overridable rank-anchor seed table (`rankAnchors`)
- Where an agent's model comes from (the role policy, a pod role overlay, a step's `model:`)
- Viewing/changing the policy (`docket setup model`)
- Automatic re-resolution of every agent on policy changes
- The built-in provider presets (`docket setup model preset`), including the free/local path
- The provider catalog (`core/provider.py`): `kind: provider` documents, the built-in/global
  scopes, and `docket-providers.json`
- Hosted OpenAI-compatible gateway endpoint and credential resolution
- Removed tier names and the private internal rank-anchor seed table
- The pricing table used for cost estimation, including local-provider and marketplace-
  provider (OpenRouter/Vercel AI Gateway) pricing honesty

This specification does NOT cover cost accumulation or budget caps (see cost-tracking.spec.md),
nor the declarative role-archetype registry itself (`name`/`scope`/`gateContract`/…, ROADMAP
Phase 16 W-6) — see role-archetypes.spec.md. This spec covers only the one integration point
between the two: how a role with no named row in this policy's table resolves via its
archetype's `modelClass` instead (see "Roles and built-in policy", requirement 5).

Provider endpoints are Docket-owned first-party configuration: `docket setup provider add`
writes `core/provider.py`'s catalog (`~/.docket/docket-providers.json`), and
`edges/adapters/llm.py` resolves that catalog entry directly — see "Provider catalog" below.
Compatibility with a retired external runtime is not part of this contract; the dated
feasibility spike remains in ROADMAP and Git history.

## Requirements

### Roles and built-in policy

1. The policy **MUST** know exactly ten roles, the archetype names (`core/archetypes.py`): the
   four built-ins `lead`, `implementer`, `reviewer`, `tester` and the six starter archetypes
   `researcher`, `analyst`, `writer`, `critic`, `operator`, `monitor`. One vocabulary names a pod
   member, its archetype and its model row; there is no separate policy name. There is no `task`
   role.
2. Each role **MUST** belong to one of two built-in classes, chosen for token efficiency:
   - **cheap** (high-volume, low reasoning density): `lead`, `reviewer`, `tester`, `monitor`,
     `analyst`, `writer` → the economy rank anchor (default `anthropic/claude-haiku-4-5`)
   - **strong** (reasoning-dense): `implementer`, `critic`, `operator`, `researcher` → the
     standard rank anchor (default `anthropic/claude-sonnet-4-6`)
3. Stronger models (opus-class) **MUST NOT** be a standing role default; they are reachable
   only through an explicit `docket setup model set <role> <provider/model>` override.
4. Each role **MUST** carry a short human-readable WHY string shown by `docket setup model`: the
   archetype's own `description`.
5. Resolving a role not in this table **MUST NOT** collapse to the compiled-in `DEFAULT_MODEL`:
   if the role is a registered pod archetype (ROADMAP Phase 16 W-6; e.g. a starter-library role
   like `researcher`, or a recipe's own role applied into a pod's overlay) whose `modelClass`
   this table has no named row for, it **MUST** resolve via that `modelClass` against the live
   rank anchors instead (`economy` for `cheap`, `standard` for `strong`) — see
   role-archetypes.spec.md. The archetype **MUST** be looked up in the registry of the pod the
   member belongs to (`core.archetypes.load_registry(project)`, which layers the pod's own
   `config/roles.json` over the global overlay), never the global registry alone, so a role a
   recipe applied into one pod resolves exactly as a global role would
   (`core.models_policy.resolve_role_model(role, role_models, project=<pod>)`). Only a role that
   is neither a named entry here nor a registered archetype in that registry **MUST** fall back
   to the registry's own `default` model (the one default of record; equal to `DEFAULT_MODEL` on
   a fresh install) — never to the compiled-in literal while an operator has set another
   default. No error, either way.
6. A project agent that is not a pod member **MUST** follow the `implementer` row
   (`models_policy.REPO_AGENT_ROLE`).

### User registry overlay

1. `~/.docket/docket-models.json` **MAY** contain a `roles` map (`role → provider/model`);
   well-formed entries **MUST** override the built-in role defaults. Unknown role names
   **MUST** be ignored silently — `load_registry` (`core/models_policy.py`) skips them with no
   warning, the same tolerance it gives a malformed `rankAnchors`/`default` entry.
2. Removed (2026-10-03): the legacy `profiles` map is no longer read or migrated; like any
   key other than `default`, `roles` and `rankAnchors`, it is ignored.
3. A corrupt registry **MUST** keep built-in defaults (no crash) and **MUST NOT** warn —
   `load_registry` falls back silently on any read/parse error.
4. The registry **MAY** contain a `rankAnchors` map (`{"economy"|"standard"|"premium":
   "provider/model"}`) that overrides the private rank-anchor seed table (see Tier names
   below) *before* role defaults are derived from it (Phase 18 L-2). This is how a fleet on
   a non-Anthropic preset stops showing Claude ids in the anchor value `docket setup model`
   displays. Unknown anchor names or malformed model ids **MUST** be ignored (same tolerance
   as `roles`/`default`).
5. Requirements 1, 3, and 4 above describe `load_registry` itself, which **MUST** keep
   resolving silently and without warning — a malformed entry must never crash a live fleet
   or a routine model resolution. Read-only and separate from that path, `docket setup`
   **MUST** run `core.models_policy.find_registry_problems` and report every entry
   `load_registry` ignored — an unknown `rankAnchors`/`roles` name, a value failing the model
   id pattern, or an unreadable/malformed registry file — naming the file and a dotted key
   locator (`rankAnchors.<anchor>`, `roles.<role>`, or `default`) plus the reason. It never
   edits the registry (ROADMAP P26-12).

### Where a member's model comes from

1. A member's model **MUST** be its role's model: the role policy, or the pod's own role overlay
   when the pod defines that role (`docket pod show` reports the source as `policy` or
   `pod overlay`). There is no per-agent pin and `.docket-meta.json` carries no `modelSource`; a
   metadata file that still has the key is read without it.
2. A model **MUST** only be set per member by provisioning (the role's resolved model) and by an
   in-place `exec` run, which sets the one model the run was given on every member of its
   ephemeral pod.
3. A pipeline step's own `model` (`pipeline-format.spec.md`'s "Steps" Requirement 10) **MUST**
   sit above the policy and the pod's role overlay, for that one hop only, and **MUST NOT**
   change `model` in `.docket-meta.json` — the member keeps following its role's model,
   entirely unaffected once the hop ends. `core.models_policy.resolve_step_model(value)` **MUST** resolve the literal rank
   words `cheap`/`strong` against the live rank anchors (`economy`/`standard` respectively, the
   same table "User registry overlay" requirement 4 already overlays) and **MUST** return any
   other value unchanged after checking that its `<provider>/…` prefix names a provider present
   in `core.provider.load_catalog()`; a prefix absent from the catalog **MUST** raise, naming the
   unknown provider, so `docket pod validate`/`plan` can refuse the step before any hop runs
   (`pod-dispatch.spec.md`'s "Per-hop execution" requirement 5) instead of failing mid-dispatch.

### Changing the policy (docket setup model)

1. `docket setup model` **MUST** list ROLE, MODEL, PRICE, SOURCE (builtin/user), and WHY for all
   seven roles, plus the default model and the rank anchors (labeled "rank anchors", not
   "fallback" — see Tier names below for why that label was corrected).
2. `docket setup model set <role> <provider/model>` **MUST** validate the model, persist the
   override to the registry, and apply it live.
3. `docket setup model preset <name>` **MUST** map the preset's cheap/strong classes onto all
   ten roles and persist them, plus the rank anchors and default.
4. After any policy change (set/preset/reset), every agent (registered or not) **MUST** be
   re-resolved to its role's new model in
   `.docket-meta.json` — the only place a model lives (ROADMAP Phase 19 P19-6: `fleet.json`
   tracks bare registration only, never a copy of `model`, so there is no second config source
   to keep in sync, and no gateway to restart since P19-7b deleted it).
5. Each policy change (`set`/`preset`/`reset`) **MUST** write one audit-log entry (the
   `models.*` action family — see audit.spec.md's Requirement 1) recording the role(s) affected
   (or `default`) and the before/after model, so the audit log alone answers "which role
   changed, from what, to what, and when" without consulting this registry file. A
   `preset`/`reset` call, which can touch every role at once, **MUST** be recorded as one entry
   listing every role's before/after pair, not one entry per role (ROADMAP Phase 15 G-4b).

### Tier names (removed, 0.2.0)

1. The tier names `economy`, `standard`, `premium` **MUST NOT** be accepted anywhere a model
   or role value is expected — `docket setup model set premium
   <model>` both **MUST** fail with an error naming a full `provider/model` id, not resolve.
   Removed in 0.2.0 per the D-2 deprecation-window exit; see ROADMAP.md D-2.
2. The three rank values survive as a private internal seed table (`_RANK_ANCHORS` in
   `core/models_policy.py`, defaulting to Anthropic ids) used to pick each role's default
   model — `economy` seeds the cheap-class roles, `standard` seeds the strong-class roles.
   "Private" means **not accepted as a CLI argument
   under the tier names** — `docket setup model set economy <model>` still fails per rule 1 above.
   It is, however, **registry-overridable** (see User registry overlay's `rankAnchors`, Phase
   18 L-2) and **is displayed** (read-only) by `docket setup model`, labeled "rank anchors" — a
   correction from the prior "fallback" label, which was a false claim: nothing in docket
   degrades a request to a cheaper model on failure. It is a role-default seed table, not a
   live runtime fallback chain, and the display now says so.
3. **Scope note (closed CL-J):** the eval harness's `docket eval --tier
   <economy|standard|premium>` flag was the one deliberately surviving user-facing use of the
   tier words (a live-eval matrix selector for spot-checks, not a model value or role key). CL-J
   removed `docket eval` (dead code wired to the retired runtime; no successor command)
   along with `tests/evals/` and eval.spec.md, so that carve-out no longer exists — tier names
   now have **zero** surviving user-facing use anywhere, closing rule 1 without exception.

### Legacy registry migration (removed)

1. Removed (2026-10-03): there is no `profiles:` → `roles:` migration. A `profiles:` key is
   ignored (User registry overlay requirement 2).
2. Removed (2026-10-03): with no migration there is no residual key to preserve.
3. Removed (2026-10-03): `docket setup` has no residual-`profiles:` advisory, and `docket setup model`
   prints no migration warning.

### Presets (docket setup model preset)

1. The built-in presets **MUST** be exactly those the built-in `templates/providers/*.yaml`
   documents declare (`core.models_policy.known_presets`), and that set **MUST** continue to
   include `anthropic` (default), `openai`, `google`, `openrouter-free`, `openrouter`,
   `ai-gateway`, and `local`. A preset menu entry **MUST NOT** require a separate `docket setup model
   provider add` first — the document that declares it is its own registration.
2. The `local` preset **MUST** require no API key (a local OpenAI-compatible endpoint —
   llama.cpp/LM Studio/vLLM/Ollama — registered separately via `docket setup provider`) and
   **MUST** price its models at `$0 (local)`.
3. Applying a preset **MUST** persist the preset's own economy/standard/premium values as the
   registry's `rankAnchors` (see User registry overlay), not just the per-role overrides — so
   the anchor value `docket setup model` displays never lags behind the fleet's actual preset after
   a non-Anthropic preset is applied.
4. `openrouter-free` **MUST** route every rank through Docket model id
   `openrouter/openrouter/free`, which transports `openrouter/free` to OpenRouter. It **MUST**
   report zero per-token price, and its note **MUST** identify the router as experimental:
   the selected model and availability can change between calls.
5. `ai-gateway` **MUST** use Docket model ids with the `ai-gateway/` prefix and retain the
   gateway's nested `creator/model` id on the wire. Marketplace prices **MUST NOT** be copied
   from a dated provider snapshot; they report `n/a (bring your own)`.

### Hosted gateway resolution

1. Docket's shipped model wire **MUST** remain the non-streaming OpenAI-compatible
   `/chat/completions` surface with function tools. A provider/model claim **MUST NOT** imply
   support for streaming, the Responses API, vendor routing options, or a model that lacks tool
   calling.
2. Without process-wide overrides, `resolve_endpoint` **MUST** resolve every built-in hosted
   gateway from its `templates/providers/*.yaml` document — `openrouter` to
   `https://openrouter.ai/api/v1` and `ai-gateway` to `https://ai-gateway.vercel.sh/v1` among
   them (the full built-in list is "Provider catalog" below). It **MUST** strip only Docket's
   first provider segment, retaining nested gateway model ids.
3. For a provider absent from the catalog, credential precedence **MUST** be:
   `DOCKET_LLM_API_KEY`, the provider's environment credential, then the same credential in
   Docket's central key store. `openrouter` uses `OPENROUTER_API_KEY`; `ai-gateway` uses
   `AI_GATEWAY_API_KEY` with `VERCEL_OIDC_TOKEN` as a fallback. For a provider present in the
   catalog, `core.provider.resolve_credential` applies the same precedence over its
   `auth.credentials` names instead — see "Provider catalog" below; a document never holds a
   credential value, so there is no placeholder-masking step.
4. `DOCKET_LLM_BASE_URL` remains a process-wide override for tests and local development. It
   **MUST** take endpoint precedence and **MUST NOT** inherit registered context/output limits from
   the endpoint it replaces. Otherwise, an exact registered model row **MUST** retain those limits.
5. Default tests **MUST** cover both hosted gateways together from public configuration semantics
   without network or real credentials. A live gateway canary is opt-in and **MUST** have an
   explicit cost/request budget.
6. A gateway response with `finish_reason: error` or an error object inside its first choice
   **MUST** produce a non-OK response. A numeric embedded status **MUST** use the same retry
   classification as that HTTP status; it **MUST NOT** become an empty successful answer.

### Provider readiness

1. Coding-harness authentication and Docket's runtime model transport **MUST** remain separate:
   Codex, Claude Code, or OpenCode subscriptions **MUST NOT** be treated as reusable provider API
   credentials or as proof that Docket can resolve a model endpoint.
2. A selected model is ready when its provider resolves in the catalog (built-in or global) to a
   base URL and every credential its `auth.credentials` names is present. A built-in hosted
   provider (Anthropic, OpenAI, Google among them) needs only its credential — its base URL is
   the shipped document, not a separate registration.
3. Registered local providers **MAY** require no bearer credential. Registration **MUST** probe
   `<base-url>/models` with the resolved credential (`core.provider.verify_endpoint` classifying
   `edges.adapters.llm.probe_models`'s result) and classify it rather than collapse it to a
   boolean: a transport failure (DNS, refused, timeout) **MUST** refuse and leave the prior
   provider catalog unchanged; every HTTP response **MUST** register instead, with a warning when
   it is not a clean 200 --- 401/403 names the missing or rejected credential, 404 states that
   `/models` is not served (capability unverified), any other status carries the status, and a 200
   whose body advertises model ids absent from `models[]` prints them as a suggestion, never
   writes them. No `--no-verify` flag exists; the classification makes one unnecessary.
4. Workstation bootstrap **MUST NOT** print a ready heading or continue into project initialization
   when the selected model is unresolved. It **MUST** name the model, explain the missing endpoint
   or credential without exposing a secret, and give the exact public configuration sequence.
5. The successful local path **MUST** report the selected model and resolved base URL, retain exact
   registered context/output limits, and reach the ordinary non-streaming Chat Completions tool
   wire. Default tests remain hermetic; the local `127.0.0.1:8081` canary is opt-in and keyless.

### The default model (single source)

1. `docket-models.json`'s `default` key **MUST** be the only default model of record. Nothing
   else is consulted — `fleet.json` has no default-model field (`FleetDefaults` is deleted), and
   a `defaults.model` left in an old file is ignored.
2. Removed (2026-10-03): there is no `fleet.json` `defaults.model` → registry migration.
3. `docket init`'s default-model step and `docket setup model set default` / `preset` / `reset`
   **MUST** write only to the registry — never to `fleet.json`.

### Provider catalog

1. A provider **MUST** be a `kind: provider` document (ADR 0011; `core.provider.ProviderSpec`):
   `name`, `dialect` (closed enum, `openai-chat` today), `baseUrl`, `auth` (`type:
   bearer|header|none` plus `credentials`, a list of names — never values, and `header`, the
   request header name a `type: header` credential rides on — required exactly when `type` is
   `header`), `headers` (a map of additional static header names to values sent verbatim on
   every request), `local`, `marketplace`, `credentialPrefix` (a credential-format hint `setup provider add`
   warns against, optional), `pricesAsOf` (`YYYY-MM-DD`, required when any model row carries a `price`),
   `models[]` (`id`, `contextWindow`, `maxTokens`, optional `price: {input, output, cacheRead,
   cacheWrite}` USD per million tokens), `presets[]` (`name`, `ranks: {economy, standard,
   premium}` as bare model ids, `note`), and `note`. `core.provider.load_provider_document`
   **MUST** raise naming the file and field on an unreadable file, bad YAML, a missing
   `kind`/`name`, an unknown `dialect`/`auth.type`, a credential count that does not match the
   `auth.type` (`header` requires at least one credential name, the same rule as `bearer`), a
   `headers` key that names `Authorization`, `Content-Type` or `Accept` (case-insensitive —
   docket sends these itself and refuses a document that tries to override them), a
   `pricesAsOf` missing while a row carries a `price`, or a malformed `pricesAsOf`/negative
   price.
2. The catalog **MUST** merge two scopes, nearest-wins by name: **built-in**
   (`config.PROVIDER_TEMPLATES_DIR`, shipped in the wheel — `anthropic`, `openai`, `google`,
   `openrouter`, `ai-gateway`, `groq`, `mistral`, `deepseek`, `xai`, `cerebras`, `together`,
   `ollama`, `lmstudio`, `local`) and **global** (`config.PROVIDERS_FILE` =
   `~/.docket/docket-providers.json`, `{"providers": {name: spec}}`, the operator's own
   registrations and overrides via `docket setup provider add`). `core.provider.load_catalog()`
   **MUST** return the merged result; `Catalog.get(name)` and `Catalog.source_of(name)`
   (`"built-in"` / `"global"` / `""`) **MUST** read it. A global write that leaves
   `presets`/`marketplace`/`credentialPrefix`/`pricesAsOf` unset **MUST** inherit each from a
   built-in of the same name (`core.provider.save_provider`), so registering a local endpoint
   under a built-in's name does not erase presets or pricing the built-in still means.
3. `docket setup provider add` **MUST** write a `ProviderSpec` to the global scope through
   `core.provider.save_provider`, never to `fleet.json`. Re-running with identical arguments
   **MUST** write nothing (idempotent). It also stores the provider's credential (flag, else its
   environment variable, else a hidden prompt on a terminal; api-keys.spec.md), probes
   `<baseUrl>/models` with it, and — unless `--no-preset` — applies the provider's preset (or, for
   a provider with none, points every role at its first model) and prints which role resolves to
   what. `--no-preset` writes no role row.
4. Removed (2026-10-03): there is no `fleet.json` `providers` → catalog migration
   (`migrate_fleet_providers` and `FleetConfig.providers` are deleted); `load_catalog()` reads
   only the built-in and global scopes, and a `providers` block left in `fleet.json` is ignored.
5. `edges/adapters/llm.py`'s `resolve_endpoint` **MUST** resolve a catalog entry's base URL and
   exact model row directly from the document, and its credential through
   `core.provider.resolve_credential`. A provider absent from the catalog **MUST** fall back to
   "Hosted gateway resolution" unchanged. `client_for` **MUST** dispatch on the entry's `dialect`
   over a closed adapter table and return `None` for a dialect with no adapter.
6. `resolve_endpoint` **MUST** carry a catalog entry's `auth.type`, `auth.header` and `headers`
   onto the resulting `core.llm.Endpoint` (`auth_type`, `auth_header`, `headers`). The adapter's
   `OpenAIChatClient._headers()` **MUST** send `Authorization: Bearer <credential>` only for
   `auth_type: bearer` with a resolved credential, `<auth_header>: <credential>` only for
   `auth_type: header` with a resolved credential, and no credential header at all for
   `auth_type: none` or an unresolved credential — then append `headers` verbatim. This covers
   Azure OpenAI's `api-key` header and a multi-workspace Anthropic key's
   `anthropic-workspace-id` without a second adapter (ADR 0011 §3). A `bearer`-auth document's
   request headers **MUST** stay byte-identical to a provider absent from the catalog.
7. **Observability.** `docket pod show <member> --json` **MUST** report, for the agent's
   resolved model, the provider's name, catalog scope (`"built-in"` / `"global"` / `""` when the
   provider is absent from the catalog), `dialect`, `baseUrl`, the resolved credential's name and
   source (`core.provider.resolve_credential`'s `"override"`/`"env"`/`"store"`/`"none"`), and the
   exact model row's `id`/`contextWindow`/`maxTokens` with a `source` of `"row"` when an exact
   row matched or `"none"` when it did not — never a credential value. The human-readable render
   **MUST** show the same provider name, scope and credential source under the model line.
   `docket setup` **MUST** report each global provider document (`config.PROVIDERS_FILE`) that
   fails the validation `core.provider.load_provider_document` applies to a file on disk — naming
   the file, the provider's name and the failing field — the same way a malformed
   `docket-roles.json` overlay entry is named, and carry the same list under `--json`.

### Pricing

1. Each built-in direct-provider model whose price Docket claims **MUST** have a `price` on its
   catalog row, in USD per million tokens (`input`/`output`/`cacheRead`/`cacheWrite`,
   `core.provider.Price`), read through `core.models_policy.price_for` and unpacked in that
   order by `core.utils.estimate_cost_usd`. Marketplace gateway models are the explicit
   exception described in requirement 4.
2. A model without pricing **MUST** report `n/a` (never $0.00) in cost output.
3. A model whose provider the catalog marks `local: true`
   (`core.models_policy.is_local_provider`) **MUST** report `$0 (local)` — this is the true
   cost, not a placeholder for missing data, and **MUST NOT** fall through to the generic `n/a`
   path.
4. A model routed through a provider the catalog marks `marketplace: true`
   (`core.models_policy.is_marketplace`; `openrouter` or `ai-gateway` among the built-ins),
   whose row carries no `price` (the explicit `openrouter/openrouter/free` router priced at
   `$0.00` is the one exception), **MUST** report a distinct, informative label
   (`n/a (bring your own)`) rather than the plain `n/a` used for an ordinary uncatalogued
   model — docket does not invent a number for pricing that changes per model/account.

## Interface Contracts

### CLI Command Signatures

```bash
docket setup model                              # Show the role→model policy
docket setup model set <role|default> <provider/model>
docket setup model preset [anthropic|openai|google|openrouter-free|openrouter|ai-gateway|local]
docket setup model reset                        # Restore built-in defaults (asks to confirm)
docket setup provider add <name> <base-url> [--model ID] [--ctx N] [--max-tokens N]
docket pod show [<member-id>]              # Each member's model and where it comes from
```

### Built-in policy (Anthropic defaults)

| Role | Class | Model | Why |
| ---- | ----- | ----- | --- |
| lead | cheap | claude-haiku-4-5 | (archetype description) |
| reviewer | cheap | claude-haiku-4-5 | (archetype description) |
| tester | cheap | claude-haiku-4-5 | (archetype description) |
| monitor | cheap | claude-haiku-4-5 | (archetype description) |
| analyst | cheap | claude-haiku-4-5 | (archetype description) |
| writer | cheap | claude-haiku-4-5 | (archetype description) |
| implementer | strong | claude-sonnet-4-6 | (archetype description) |
| critic | strong | claude-sonnet-4-6 | (archetype description) |
| operator | strong | claude-sonnet-4-6 | (archetype description) |
| researcher | strong | claude-sonnet-4-6 | (archetype description) |

The role set above is `ALL_ROLES` (`core/models_policy.py`), keyed identically to `ROLE_CLASS`.
A `docket-models.json` `roles:` key that is not one of these names is ignored at read time and
reported by `docket setup`; nothing rewrites the file. A pod-scoped archetype with no row
resolves per requirement 5.

### Pricing Table (USD per MTok, Anthropic defaults)

| Class | Model | Input | Output |
| ----- | ----- | ----- | ------ |
| cheap | claude-haiku-4-5 | 0.80 | 4.00 |
| strong | claude-sonnet-4-6 | 3.00 | 15.00 |
| (premium anchor) | claude-opus-4-6 | 15.00 | 75.00 |

Pricing is a manual snapshot (`MODEL_PRICING`, dated by `MODEL_PRICING_AS_OF`) used for
display and comparative estimates only — recorded spend comes from measured token counts in
docket's own per-session storage (ROADMAP Phase 19 P19-4/P19-7b; `_cfg.SESSIONS_DIR`, see
cost-tracking.spec.md), not a daemon. The table carries a `local/qwen3-30b-a3b` row and the
`openrouter/openrouter/free` router at zero (the router contract, not a dated selection of free
models); `LOCAL_PROVIDERS`
(`local`, `ollama`, `lmstudio`) independently price at `$0 (local)` regardless of whether the
specific model id is catalogued. Paid OpenRouter and AI Gateway preset models are deliberately
left uncatalogued — gateways can route and re-price by provider/account — and report
`n/a (bring your own)` instead.

### Registry file shape (current)

```json
{
  "default": "anthropic/claude-sonnet-4-6",
  "roles":       { "implementer": "openai/gpt-4.1" },
  "rankAnchors": { "standard": "openai/gpt-4.1-mini" }
}
```

`default`, `roles`, and `rankAnchors` are the only keys `models_policy.load_registry` reads.
There is no user pricing overlay: prices come only
from the built-in `MODEL_PRICING` snapshot, and any other key is ignored.

### Return Codes

Like every other docket command (see cli-interface.spec.md), `docket setup model` uses a plain
success/failure contract — `0` on success, `1` on any error (invalid model, unknown role). There is no distinct exit code per error kind.

## Examples

### Viewing and changing the policy

```bash
$ docket setup model
  ROLE          MODEL                        PRICE          SOURCE    WHY
  lead          anthropic/claude-haiku-4-5   $0.80/$4.00    builtin   orchestrates the pod; never edits code
  implementer    anthropic/claude-sonnet-4-6  $3.00/$15.00   builtin   writes code in the project workspace
  ...

$ docket setup model set implementer openai/gpt-4.1
✓ implementer → openai/gpt-4.1

→ Re-resolving policy-following agents...
  1 agent(s) updated.
```

The count line is printed only when at least one policy-following agent changed;
`models_policy.reapply_role_policy` returns a count and `core/` never prints per-agent lines.

### Switching the whole fleet to a free/local preset

```bash
$ docket setup model preset local
✓ Preset 'local' applied.

→ Re-resolving policy-following agents...

✓ Registered local endpoint selected; no API key needed.
  ...

$ docket setup model
  ROLE          MODEL                    PRICE        SOURCE    WHY
  lead          local/qwen3-30b-a3b      $0 (local)   user      orchestrates the pod; never edits code
  implementer   local/qwen3-30b-a3b      $0 (local)   user      writes code in the project workspace
  ...
  default       local/qwen3-30b-a3b
  rank anchors  local/qwen3-30b-a3b → local/qwen3-30b-a3b → local/qwen3-30b-a3b
  (role-default seed table — not a runtime fallback chain; overridable in docket-models.json)
```

## Validation

### Pre-conditions

- The role **MUST** be known (models set).

### Post-conditions

- After a policy change, `.docket-meta.json` `model` **MUST** reflect the new value —
  the only place a model lives (ROADMAP Phase 19 P19-6: `fleet.json`'s `FleetAgent` tracks bare
  registration only, never a copy of `model`, so there is no second location to keep in sync).

### Invariants

- A role **MUST** always resolve to exactly one model id.
- Pricing **MUST** exist for every built-in model that Docket displays with a numeric price;
  marketplace routes may use the explicit unpriced label above.

## Changelog

### Version 3.2.1 (2026-10-08)

- Command names follow ADR 0022.

### Version 3.2.0 (2026-10-08)

- Phase 39 (P39-10): the per-agent pin is removed. `docket profile` is gone, `modelSource` is no
  longer written or read (`core.models_policy.agent_model_source` and the pinned branch of
  `reapply_role_policy` are deleted; a stored `modelSource` is ignored), and a policy change
  re-resolves every agent. A model comes from the role policy, a pod role overlay or a step's
  `model:`; `docket pod show` reports which. `config explain` becomes `docket pod show <member>`.

### Version 3.1.0 (2026-10-07)

- Phase 39 (P39-12): the policy surface is `docket setup model` (`list`, `set`, `preset`, `reset`) and
  endpoints are `docket setup provider`; `provider add` is the whole intent (credential, probe,
  registration, preset) and takes `--no-preset`. `docket models` and `docket models provider` are
  unknown commands.

### Version 3.0.1 (2026-10-07)

- `reapply_role_policy` (what `models preset`, `set` and `reset` run over policy-following
  agents) resolves each agent through `resolve_role_model(..., project=)`, so a pod-scoped
  archetype with no row follows the registry default, never `cfg.DEFAULT_MODEL`. Found on the
  live home: `models preset local` rewrote a `security-vetter` member to the compiled-in
  Anthropic id.

### Version 3.0.0 (2026-10-07)

- **One role vocabulary.** The policy's roles are the ten archetype names; `manager`, `programmer`,
  `knowledge`, `security` and `repo` are removed with no alias, and `docket-models.json` is not
  migrated (an unknown `roles:` key is ignored and reported by `doctor`). `ROLE_CLASS` is keyed the
  same way; `docket models` prints the archetype names and its WHY column is the archetype
  description; `preset` writes archetype-keyed rows; org specialists no longer have a policy row.

### Version 2.18.0 (2026-10-03)

- **Legacy purge: every one-shot migration is deleted.** The `profiles:` → `roles:` registry
  migration (with `has_residual_profiles_key`, the doctor advisory and the `docket models`
  warning), the `fleet.json` `defaults.model` → registry migration (`FleetDefaults`, fleet's
  `get/set_default_model`), and the `fleet.json` `providers` → catalog migration
  (`migrate_fleet_providers`, `FleetConfig.providers`) are gone; their requirements are marked
  removed and the legacy registry example is dropped. Old keys are ignored. `MODEL_ALIASES` (old
  Anthropic ids rewritten by `validate_model`) and doctor's stale-model check are deleted too.
  "Model intent" requirement 3: `modelSource` is still inferred on read, but `docket doctor` no
  longer backfills it.

### Version 2.17.0 (2026-09-27)

- **"Roles and built-in policy" requirement 5 amended (Phase 30, found by running the product):**
  a pod-scoped archetype (a recipe's own role applied into `config/roles.json`) was resolved
  against the global registry only, so `security-vetter` with `model: strong` fell to the
  compiled-in `DEFAULT_MODEL` (`anthropic/claude-sonnet-4-6`) on a fleet whose preset and rank
  anchors were `local`, and the hop hit the hosted vendor with no key. `resolve_role_model`
  gains a keyword-only `project` that `core/pod.py::resolve_member`, `core/pod_apply.py`'s
  member planning and `docket profile <id> default` pass; the last-resort fallback is the
  registry's `default` model, not the literal.

### Version 2.16.0 (2026-09-27)

- **P30-3: a pipeline step's own model wins for one hop, above policy and pin (ADR 0012 §2 rule
  6).** New "Model intent per agent" requirement 4 and `core.models_policy.resolve_step_model`:
  resolves `cheap`/`strong` against the live rank anchors, returns any other value unchanged after
  confirming its provider is in the catalog, and raises naming the provider when it is not. Never
  writes `.docket-meta.json` — `modelSource`/`model` keep reporting the agent's own standing
  resolution; `docket profile`/`config explain` are unaffected.

### Version 2.15.0 (2026-09-27)

- **P29-6: `config explain` names the provider and its scope, and `doctor` names a malformed
  global document.** Before this, `docket config explain` reported a resolved model id and
  nothing about where it goes -- an operator had to trace `resolve_endpoint`, `load_catalog` and
  `resolve_credential` by hand to find out. Added "Provider catalog" requirement 7
  (observability): `config explain --json` gains a `provider` block (name, scope, dialect,
  baseUrl, credential name/source, exact model row) built from `resolve_endpoint`,
  `Catalog.source_of` and `resolve_credential`; a provider absent from the catalog still gets a
  block, with `scope: ""`. `docket doctor` gains a check over every global provider document,
  naming the file, provider name and failing field the same way a malformed `docket-roles.json`
  overlay entry is named, and carries the same list under `--json`.

### Version 2.14.0 (2026-09-27)

- **P29-4: a provider can authenticate by header and send static headers.** `AuthSpec.type`
  gains `header` (`"bearer" | "header" | "none"`), plus `header: str`, the request header name a
  `type: header` credential rides on, required exactly when `type` is `header`.
  `ProviderSpec.headers: dict[str, str]` sends additional static headers verbatim; a document
  naming `Authorization`, `Content-Type` or `Accept` (case-insensitive) is refused, naming
  `headers`. `load_provider_document`'s credential-count check now treats `header` the same as
  `bearer` (at least one credential name). `core.llm.Endpoint` gains `auth_type`, `auth_header`
  and `headers` (a tuple of pairs, so the frozen dataclass stays hashable) and loses `is_local`
  (no consumer outside one test). Amended "Provider catalog" requirement 1 (the `auth`/`headers`
  fields and the new refusal) and added requirement 6 (`resolve_endpoint` fills the three fields
  from the document; `OpenAIChatClient._headers()` sends the credential under `Authorization:
  Bearer`, a named header, or not at all, then appends `headers` — a bearer document's request
  stays byte-identical to today). This unblocks Azure OpenAI's `api-key` header and a
  multi-workspace Anthropic key's `anthropic-workspace-id` without a second adapter (ADR 0011
  §3), with no new dependency and no change to a `bearer`-auth document's wire behaviour.
### Version 2.13.0 (2026-09-27)

- **P29-3: registration verifies with the credential, and a provider round-trips through the
  CLI.** Amended "Provider readiness" 3: registration now probes `<base-url>/models` **with the
  resolved credential** and classifies the response (ADR 0011 §4) instead of collapsing it to a
  boolean -- only a transport failure refuses; every HTTP status registers, with a warning when
  it is not a clean 200 (401/403 names the credential, 404 says the route is unserved, a 200 with
  unknown ids suggests them without writing them). `core.provider.verify_endpoint` is the pure
  classifier; `edges.adapters.llm.probe_models` is the one function that opens the socket;
  `register_provider`/`remove_provider`/`export_provider` replace `register_local_provider`/
  `ping_endpoint`/`ProviderRegistration`, which are removed along with the `DEFAULT_PROVIDER`/
  `DEFAULT_BASE_URL`/`DEFAULT_MODEL_ID`/`DEFAULT_MODEL_NAME`/`DEFAULT_CTX`/`DEFAULT_MAX_TOKENS`
  constants -- the bare `add` shortcut's defaults now come from the built-in `local` document.
  Closes the CLI/HTTP asymmetry where `docket models provider add`/`list`/`show`/`remove`/
  `export` existed only as a plan: only `add` (as a single-model shortcut) was reachable before
  this card.

### Version 2.12.0 (2026-09-27)

- **P29-2: the providers docket knows are documents, and every table derives from them.**
  `ProviderSpec` gains `presets[]`, `marketplace`, `credentialPrefix`, `pricesAsOf`, and
  `ModelRow.price`; `src/docket/templates/providers/*.yaml` ships fourteen built-in documents
  (`anthropic`, `openai`, `google`, `openrouter`, `ai-gateway`, `groq`, `mistral`, `deepseek`,
  `xai`, `cerebras`, `together`, `ollama`, `lmstudio`, `local`), replacing the hand-kept
  `KNOWN_PRESETS`/`PRESET_TABLE`/`LOCAL_PROVIDERS`/`UNPRICED_MARKETPLACE_PROVIDERS`/
  `MODEL_PRICING`/`MODEL_PRICING_AS_OF`/`_RANK_ANCHORS` constants with
  `core.models_policy.presets`/`preset_table`/`known_presets`/`is_local_provider`/
  `is_marketplace`/`price_for`/`prices_as_of`/`rank_anchors`, functions over the loaded catalog.
  Amended "Presets" 1 (the built-in set is what the catalog declares), "Hosted gateway
  resolution" 2 (every built-in hosted URL is a shipped document), "Provider readiness" 2 (a
  built-in hosted provider needs only its credential — no separate registration), and "Pricing"
  1/3/4 (keyed to catalog rows, `local: true`, `marketplace: true`). `edges/adapters/llm.py`'s
  `_HOSTED_GATEWAY_BASE_URLS` and `core.provider.PROVIDER_CREDENTIAL_NAMES` are gone: a provider
  absent from the catalog resolves only under `DOCKET_LLM_BASE_URL`, deriving
  `<PREFIX>_API_KEY`. `cli/_doctor.py`'s `_PROVIDER_KEY` and `cli/_keys.py`'s `_KEY_PREFIXES`
  are gone too, replaced by catalog reads (`credentialPrefix`, `auth.credentials`). Closes the
  regression where `docket models preset anthropic|openai|google|local` refused for lack of a
  separate registration the built-in document now supplies.

### Version 2.11.0 (2026-09-27)

- **P29-1: a provider is a document, and today's configuration resolves exactly as before.**
  Added "Provider catalog": `core/provider.py::ProviderSpec`/`Catalog`/`load_catalog`/
  `save_provider`/`resolve_credential`, the built-in/global scopes, `docket-providers.json`, and
  the one-shot `fleet.json -> providers` migration (a literal `apiKey` moves into the secret
  store, audited `provider.migrate`). Amended "Hosted gateway resolution" rule 3: the
  "non-placeholder key in the provider block" step is gone — a document never holds a value; a
  catalog entry resolves its credential through `resolve_credential` instead, over the same
  precedence. **Removed** "Provider registration display fields": the per-model `name`/`cost`/
  `reasoning`/`input` fields and the block's `api` field had no field in the new document and no
  reader — `ProviderSpec.models[]` carries only `id`/`contextWindow`/`maxTokens`. Fixed the
  Scope paragraph's claim that `provider add` writes `fleet.json`; it writes the catalog.
  `core/fleet.py::add_local_provider`/`get_local_provider` are removed; `FleetConfig.providers`
  is read once by the migration, then cleared (removal deferred one release, ADR 0011).

### Version 2.10.0 (2026-09-26)

- Added "The default model (single source)": `docket-models.json`'s `default` is now the only
  default model of record. `fleet.json`'s `defaults.model` (the org-wide default `docket init`
  used to write) is ported into the registry on first read when the registry has no `default` of
  its own yet, then cleared — `core/fleet.py`'s `get_default_model`/`set_default_model` delegate to
  the registry and never read or write the fleet field again. Closes the gap where `models set
  default`/`models preset` changed the registry but left the fleet copy stale, so the hidden
  `_json default-model-get` bridge (`cli/__init__.py`) answered from the wrong source.
- Added "Provider registration display fields": `docket models provider add --model <id>` with no
  `--name` now labels the entry after `<id>` instead of always defaulting to the shipped
  "Qwen3 30B-A3B (local)" caption; the per-model `name`/`cost`/`reasoning`/`input` fields and the
  provider block's `api` field are documented as display-only, matching what
  `edges/adapters/llm.py`'s `resolve_endpoint` actually reads.

### Version 2.9.0 (2026-09-26)

- **P26-12: configuration errors are loud.** "User registry overlay" gains requirement 5:
  `load_registry` itself keeps ignoring a malformed `rankAnchors`/`default`/`roles` entry
  silently (requirements 1, 3, 4 are unchanged — a live fleet must never crash on a bad
  registry), but `docket doctor` now runs a separate, read-only check
  (`core.models_policy.find_registry_problems`) naming the file, a dotted key locator, and
  the reason for every entry it ignored. See `pod-dispatch.spec.md` v6.13.0 for the
  companion `docket-schedules.json` writer and `role-archetypes.spec.md` v1.10.0 for the
  matching `docket-roles.json` overlay check this same card added.

### Version 2.8.2 (2026-09-21)

- User registry overlay requirements 1 and 3 corrected: unknown roles and a corrupt registry are ignored silently by `load_registry`, not reported with a warning (W36-C11).

### Version 2.8.1 (2026-09-19)

- Doc-truth pass, no behavior change. Corrected the pricing-tuple order to
  `input:output:cacheRead:cacheWrite` (what `MODEL_PRICING` stores and `estimate_cost_usd`
  unpacks). Removed the `pricing` key from the current registry-shape example: nothing reads it,
  and the shape now names the keys `load_registry` actually reads. Replaced the `models set`
  example's invented per-agent line with the real `N agent(s) updated.` count, added the
  re-resolve line to the preset example, and added `docket models provider add` to the command
  signatures that Scope already covered.

### Version 2.8.0 (2026-08-30)

- Added fail-closed first-run provider readiness. Coding-tool subscriptions are not runtime API
  credentials; direct vendor keys require a registered compatible endpoint, while a reachable
  registered local endpoint may operate without a key.
- Required provider registration to avoid persisting unreachable endpoints and made the keyless
  local OpenAI-compatible tool path the bounded live acceptance route.

### Version 2.7.0 (2026-08-25)

- Added first-party hosted resolution for OpenRouter and Vercel AI Gateway, including nested model
  ids, central-store/environment credential precedence, exact registered limits, and hermetic
  dual-gateway acceptance.
- Replaced the stale curated `openrouter-free` list with OpenRouter's stable `openrouter/free`
  router and added an `ai-gateway` preset using current creator/model ids.
- Corrected the contradictory opening role count to the seven-role `ALL_ROLES` contract already
  stated by the interface and implementation.

### Version 2.6.0 (2026-08-19)

- W21-C1 daemon-free truth pass: removed the superseded provider-compatibility spike from the
  current contract. Provider registration is now stated once as Docket-owned `fleet.json` state
  resolved directly by the LLM adapter; historical evidence remains in ROADMAP and Git history.

### Version 2.5.2 (2026-08-04)

- **CL-J — `docket eval` removed.** Closed the "Scope note" carve-out under Tier names (removed,
  0.2.0): `docket eval --tier` was the one deliberately surviving user-facing use of the tier
  vocabulary, and CL-J deleted `docket eval` outright (dead code wired to the deleted OpenClaw
  daemon; no successor command, unlike `docket workflow`/`docket team`). Tier names now have zero
  surviving user-facing use anywhere.

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
  `manager`/`programmer`/`reviewer`/`tester` rows exactly as before (superseded by 3.0.0). No new hardcoded role name
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
