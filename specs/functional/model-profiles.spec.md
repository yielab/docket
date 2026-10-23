# Model Policy Specification

**Version**: 5.0.3
**Status**: Complete. A pipeline step's `model:` sits above the role policy for one hop and is
never persisted (see "Where a member's model comes from" requirement 3).
**Last Updated**: 2026-10-23

## Purpose

This specification defines the **role→model policy** that decides which model every kind of
agent runs on, and how policy changes propagate to the fleet. A model comes from exactly three
layers: the role policy, a pod's own role overlay, and a pipeline step's `model:`. The tier names
`economy`, `standard` and `premium` are rank-anchor names only; they are never accepted as a model
or a role value.

## Scope

This specification covers:

- The agent roles the policy knows about and their built-in model classes
- The user registry overlay (`~/.docket/docket-models.json`), including the overridable
  rank-anchor table (`rankAnchors`)
- Where an agent's model comes from (the role policy, a pod role overlay, a step's `model:`)
- Viewing/changing the policy (`docket setup model`)
- Automatic re-resolution of every agent on policy changes
- The built-in provider presets (`docket setup model preset`), including the free/local path
- The provider catalog: `kind: provider` documents, the built-in and global scopes, and
  `~/.docket/docket-providers.json`
- Endpoint and credential resolution, including the hosted OpenAI-compatible gateways
- Rank-anchor names versus the model and role values a command accepts
- Cost labels derived from the catalog, including local-provider and marketplace-provider
  (OpenRouter/Vercel AI Gateway) pricing honesty

This specification does NOT cover cost accumulation or budget caps (see cost-tracking.spec.md),
nor the declarative role-archetype registry itself (`name`/`scope`/`gateContract`/…) — see
role-archetypes.spec.md. This spec covers only the one integration point between the two: how a
role with no named row in this policy's table resolves via its archetype's `modelClass` instead
(see "Roles and built-in policy", requirement 5).

Provider endpoints are Docket-owned first-party configuration: `docket setup provider add` writes
the global catalog (`~/.docket/docket-providers.json`), and endpoint resolution reads that catalog
directly — see "Provider catalog" below.

## Requirements

### Roles and built-in policy

1. The policy **MUST** know exactly ten roles, the archetype names: the four built-ins `lead`,
   `implementer`, `reviewer`, `tester` and the six starter archetypes `researcher`, `analyst`,
   `writer`, `critic`, `operator`, `monitor`. One vocabulary names a pod member, its archetype and
   its model row; there is no separate policy name. There is no `task` role.
2. Each role **MUST** belong to one of two built-in classes, chosen for token efficiency:
   - **cheap** (high-volume, low reasoning density): `lead`, `reviewer`, `tester`, `monitor`,
     `analyst`, `writer` → the economy rank anchor (default `anthropic/claude-haiku-4-5`)
   - **strong** (reasoning-dense): `implementer`, `critic`, `operator`, `researcher` → the
     standard rank anchor (default `anthropic/claude-sonnet-4-6`)

   This table (`ROLE_CLASS`) is built from the `modelClass` of the ten archetypes, so
   `docket pod roles` and the policy report one class per role.
3. Stronger models (opus-class) **MUST NOT** be a standing role default; they are reachable
   only through an explicit `docket setup model set <role> <provider/model>` override.
4. Each role **MUST** carry a short human-readable WHY string shown by `docket setup model`: the
   archetype's own `description`.
5. Resolving a role not in this table **MUST NOT** collapse to the compiled-in `DEFAULT_MODEL`:
   if the role is a registered archetype (a role a recipe applied into a pod's overlay) whose `modelClass` this table has no named row for, it **MUST** resolve via that
   `modelClass` against the live rank anchors instead (`economy` for `cheap`, `standard` for
   `strong`) — see role-archetypes.spec.md. The archetype **MUST** be looked up in the registry of
   the pod the member belongs to (the pod's `config/roles.json` layered over the built-ins and the
   starter library), never the built-in registry alone, so a role a recipe applied into one pod
   resolves through its own `modelClass`
   (`resolve_role_model(role, role_models, project=<pod>)`). Only a role that is neither a named
   entry here nor a registered archetype in that registry **MUST** fall back to the registry's own
   `default` model (the one default of record; equal to `DEFAULT_MODEL` on a fresh install) —
   never to the compiled-in literal while an operator has set another default. No error, either
   way. A pod overlay that redefines one of the ten named roles does not change its model: the
   named row wins.
6. A project agent that is not a pod member **MUST** follow the `implementer` row.

### User registry overlay

1. `~/.docket/docket-models.json` **MAY** contain a `roles` map (`role → provider/model`);
   well-formed entries **MUST** override the built-in role defaults. Unknown role names
   **MUST** be ignored silently — `load_registry` skips them with no warning, the same tolerance
   it gives a malformed `rankAnchors`/`default` entry.
2. Any key other than `default`, `roles` and `rankAnchors` **MUST** be ignored (a retired
   `profiles` map included).
3. A corrupt registry **MUST** keep built-in defaults (no crash) and **MUST NOT** warn —
   `load_registry` falls back silently on any read/parse error.
4. The registry **MAY** contain a `rankAnchors` map (`{"economy"|"standard"|"premium":
   "provider/model"}`) that overrides the rank-anchor table (see "Rank anchors and tier names"
   below) *before* role defaults are derived from it. This is how a fleet on a non-Anthropic
   preset stops showing Claude ids in the anchor value `docket setup model` displays. Unknown
   anchor names or malformed model ids **MUST** be ignored (same tolerance as `roles`/`default`).
   A model id is well-formed when it matches `^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$`.
5. Requirements 1, 3, and 4 above describe `load_registry` itself, which **MUST** keep
   resolving silently and without warning — a malformed entry must never crash a live fleet
   or a routine model resolution. Read-only and separate from that path, `docket setup`
   **MUST** run `find_registry_problems` and report every entry `load_registry` ignored — an
   unknown `rankAnchors`/`roles` name, a value failing the model id pattern, a non-object
   `rankAnchors`/`roles`, or an unreadable/malformed registry file — naming the file and a dotted
   key locator (`rankAnchors.<anchor>`, `roles.<role>`, or `default`) plus the reason. It never
   edits the registry.

### Where a member's model comes from

1. A member's model **MUST** be its role's model: the role policy, or the pod's own role overlay
   when the pod defines that role (`docket pod show` reports the source as `policy` or
   `pod overlay`). There is no per-agent pin; nothing reads a `modelSource` key from
   `.docket-meta.json`.
2. A model **MUST** only be set per member by provisioning (the role's resolved model).
3. A pipeline step's own `model` (`pipeline-format.spec.md`'s "Steps" Requirement 10) **MUST**
   sit above the policy and the pod's role overlay, for that one hop only, and **MUST NOT**
   change `model` in `.docket-meta.json` — the member keeps following its role's model,
   entirely unaffected once the hop ends. `resolve_step_model(value)` **MUST** resolve the literal
   rank words `cheap`/`strong` against the live rank anchors (`economy`/`standard` respectively,
   the same table "User registry overlay" requirement 4 overlays) and **MUST** return any other
   value unchanged after checking that its `<provider>/…` prefix names a provider present in the
   provider catalog; a prefix absent from the catalog **MUST** raise, naming the unknown provider.
   `docket pod validate` **MUST** refuse a pipeline whose step names such a provider, naming the
   step; a dispatch that reaches that hop anyway fails the hop with an error naming the step
   (`pod-dispatch.spec.md`'s "Per-hop execution" requirement 5). `docket pod plan` does not check
   it.

### Changing the policy (docket setup model)

1. `docket setup model` (also `docket setup model list`, with `--json`) **MUST** list ROLE,
   MODEL, PRICE, SOURCE (`builtin`/`user`), and WHY for all ten roles, in the order `lead`,
   `implementer`, `reviewer`, `tester`, `researcher`, `analyst`, `writer`, `critic`, `operator`,
   `monitor`, plus the default model and the rank anchors (labeled "rank anchors", printed
   premium → standard → economy; see "Rank anchors and tier names"). SOURCE is `user` when the
   registry's `roles` map holds the role's current model, else `builtin`. `--json` emits
   `{"roles": [{role, model, price, source, why}], "default": <model>}`.
2. `docket setup model set <role|default> <provider/model>` **MUST** validate the model, persist
   the override to the registry, and apply it live. A key that is neither one of the ten roles nor
   `default` **MUST** fail naming the valid keys; a model that is not a well-formed
   `provider/model` id **MUST** fail naming the full-id form. Both exit 1 and write nothing.
3. `docket setup model preset <name>` **MUST** map the preset's cheap/strong classes onto all
   ten roles (economy rank to the six cheap roles, standard rank to the four strong roles) and
   persist them, plus the rank anchors and `default` (set to the standard rank). With no name it
   lists the presets (PRESET, COST, KEY NEEDED, NOTE); an unknown name exits 1 listing the valid
   ones.
4. After a change to a role row, a preset, or a reset, every agent (registered or not — every
   workspace carrying a `.docket-meta.json`) **MUST** be re-resolved to its role's new model in
   `.docket-meta.json` — the only place a model lives; `fleet.json` tracks bare registration only
   and never holds a copy of `model`, so there is no second config source to keep in sync.
   `docket setup model set default` writes the registry only and re-resolves nothing.
5. Each policy change (`set`/`preset`/`reset`) **MUST** write one audit-log entry (the
   `models.*` action family — see audit.spec.md's Requirement 1) recording the role(s) affected
   (or `default`) and the before/after model, so the audit log alone answers "which role
   changed, from what, to what, and when" without consulting this registry file. A
   `preset`/`reset` call, which can touch every role at once, **MUST** be recorded as one entry
   listing every role's before/after pair, not one entry per role.

### Rank anchors and tier names

1. The tier names `economy`, `standard`, `premium` **MUST NOT** be accepted anywhere a model
   or role value is expected: `docket setup model set premium <model>` fails with `Unknown
   role`, and `docket setup model set <role> premium` fails with an error naming a full
   `provider/model` id. Neither resolves.
2. The three names are the rank anchors: the default model for each rank, read from the
   `anthropic` provider's own `anthropic` preset (Anthropic ids by default). `economy` seeds the
   cheap-class roles, `standard` seeds the strong-class roles. They are valid only as the keys of
   the registry's `rankAnchors` map and of a preset's `ranks`; a model id is never spelled with
   them. The anchors are **registry-overridable** (see "User registry overlay" requirement 4) and
   are displayed (read-only) by `docket setup model`, labeled "rank anchors". They are a
   role-default table, not a live runtime fallback chain: nothing in docket degrades a request
   to a cheaper model on failure. When the `anthropic` provider's `anthropic` preset (the
   built-in or a global document of that name) does not rank `economy` and `standard`,
   `load_registry` **MUST** raise a `DocumentError` naming the file, the field and the missing
   anchor, and `docket setup provider add` **MUST** refuse such a document (exit 1) before it
   stores a credential or writes the catalog.

### Presets (docket setup model preset)

1. The presets **MUST** be exactly those the catalog's provider documents declare
   (`known_presets`), and that set **MUST** continue to include `anthropic` (default), `openai`,
   `google`, `openrouter-free`, `openrouter`, `ai-gateway`, and `local`. A preset menu entry
   **MUST NOT** require a separate `docket setup provider add` first — the document that declares
   it is its own registration.
2. The `local` preset **MUST** require no API key (a local OpenAI-compatible endpoint —
   llama.cpp/LM Studio/vLLM/Ollama — registered separately via `docket setup provider add`) and
   **MUST** price its models at `$0 (local)`. When a global provider document named `local` is
   registered with a model row, the preset **MUST** use `local/<its first model id>` for all three
   ranks instead of the preset's own model.
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
2. Without process-wide overrides, `resolve_endpoint` **MUST** resolve every provider in the
   catalog from its document — the built-in hosted gateways `openrouter` (`https://openrouter.ai/api/v1`)
   and `ai-gateway` (`https://ai-gateway.vercel.sh/v1`) among them (the full built-in list is
   "Provider catalog" below). It **MUST** strip only Docket's first provider segment, retaining
   nested gateway model ids. A provider absent from the catalog resolves to no endpoint unless
   `DOCKET_LLM_BASE_URL` is set.
3. For a provider in the catalog, credential precedence **MUST** be: `DOCKET_LLM_API_KEY`; then
   each name in the document's `auth.credentials`, in order, in the process environment; then the
   same names, in order, in Docket's central key store. `openrouter` uses `OPENROUTER_API_KEY`;
   `ai-gateway` uses `AI_GATEWAY_API_KEY` with `VERCEL_OIDC_TOKEN` as a second name (an
   environment value for either outranks a stored one). A document never holds a credential
   value, so there is no placeholder-masking step. When `DOCKET_LLM_BASE_URL` resolves a model
   (including one whose provider is absent from the catalog), the credential is
   `DOCKET_LLM_API_KEY`, else the environment variable `<PROVIDER>_API_KEY` (the provider name
   upper-cased, `-` as `_`), else that name in the central key store.
4. `DOCKET_LLM_BASE_URL` remains a process-wide override for tests and local development. It
   **MUST** take endpoint precedence over the catalog (the catalog entry's auth type, extra
   headers and limits do not apply) and **MUST NOT** inherit registered context/output limits from
   the endpoint it replaces. Otherwise, an exact registered model row **MUST** retain those limits.
5. Default tests **MUST** cover both hosted gateways together from public configuration semantics
   without network or real credentials. A live gateway canary is opt-in and **MUST** have an
   explicit cost/request budget.
6. A gateway response with `finish_reason: error` or an error object inside its first choice
   **MUST** produce a non-OK response. A numeric embedded status **MUST** use the same retry
   classification as that HTTP status; it **MUST NOT** become an empty successful answer. A
   top-level `error` object, or a body with no choices, is likewise a non-OK response.

### Provider readiness

1. Coding-harness authentication and Docket's runtime model transport **MUST** remain separate:
   Codex, Claude Code, or OpenCode subscriptions **MUST NOT** be treated as reusable provider API
   credentials or as proof that Docket can resolve a model endpoint.
2. A selected model is ready when an endpoint resolves for it and, if its provider's document names
   credentials, at least one of them resolves to a value. A built-in hosted provider (Anthropic,
   OpenAI, Google among them) needs only its credential — its base URL is the shipped document,
   not a separate registration. Readiness is structural: it spends no model request.
3. Registered local providers **MAY** require no bearer credential. Registration **MUST** probe
   `<base-url>/models` with the resolved credential (`verify_endpoint` classifying
   `probe_models`'s result) and classify it rather than collapse it to a boolean: a transport
   failure (DNS, refused, timeout) **MUST** refuse and leave the prior provider catalog and the
   credential store unchanged (a credential is stored only after the probe got an answer);
   every HTTP response **MUST** register instead, with a warning when it is not a clean 200 ---
   401/403 names the missing or rejected credential, 404 states that `/models` is not served
   (capability unverified), any other status carries the status, and a 200 whose body advertises
   model ids absent from `models[]` prints them as a suggestion, never writes them. No
   `--no-verify` flag exists; the classification makes one unnecessary.
   When `docket setup provider add` is given a custom endpoint (no catalog entry) and no
   `--model`, it **MUST** probe once, record the first advertised id (sorted) as the row in place
   of `local-model`, and name it in the success output; when a 200 advertises nothing the row stays
   `local-model` and the output says no model was advertised. `--model` always wins.
4. Bare `docket setup` **MUST** report, for the `lead` and `implementer` roles, the selected model
   and why it is unresolved (the missing endpoint or credential, never a secret), give the
   command `docket setup provider add <name>`, print no `Ready.` line, and exit 1 off a terminal
   (`--json` carries `ready: false`). `docket init` provisions the pod regardless, then warns `No
   model endpoint yet` and points at `docket setup`.
5. `docket pod show <member>` **MUST** report the selected model, the resolved base URL, whether
   the endpoint is ready (and the issue when it is not), and the exact registered context/output
   limits (the limits in `--json`). The resolved endpoint reaches the ordinary non-streaming Chat Completions tool wire.
   Default tests remain hermetic; the local `127.0.0.1:8081` canary is opt-in and keyless.

### The default model (single source)

1. `docket-models.json`'s `default` key **MUST** be the only default model of record. Nothing
   else is consulted — `fleet.json` has no default-model field, and a `defaults.model` in a
   `fleet.json` is ignored. When the key is absent the compiled-in `DEFAULT_MODEL` applies.
2. `docket setup model set default` / `preset` / `reset` and `docket setup provider add` (which
   applies a preset, or points every role at the provider's first model) **MUST** write only to
   the registry — never to `fleet.json`.

### Provider catalog

1. A provider **MUST** be a `kind: provider` document (ADR 0011; `ProviderSpec`):
   `name`, `dialect` (closed enum, `openai-chat` today), `baseUrl`, `auth` (`type:
   bearer|header|none` plus `credentials`, a list of names — never values, and `header`, the
   request header name a `type: header` credential rides on — required exactly when `type` is
   `header`), `headers` (a map of additional static header names to values sent verbatim on
   every request), `local`, `marketplace`, `credentialPrefix` (a credential-format hint `setup provider add`
   warns against, optional), `pricesAsOf` (`YYYY-MM-DD`, required when any model row carries a `price`),
   `models[]` (`id`, optional declared `contextWindow`/`maxTokens`, optional `price: {input, output, cacheRead,
   cacheWrite}` USD per million tokens; no built-in document declares a limit), `presets[]` (`name`, `ranks: {economy, standard,
   premium}` as bare model ids, `note`), and `note`. A document with `local: true` and no `auth`
   takes `auth.type: none`. `load_provider_document` **MUST** raise naming the file and field on
   an unreadable file, bad YAML, a missing `kind`/`name`, an unknown `dialect`/`auth.type`, a
   credential count that does not match the `auth.type` (`header` requires at least one
   credential name, the same rule as `bearer`; `none` accepts none), a `headers` key that names
   `Authorization`, `Content-Type` or `Accept` (case-insensitive — docket sends these itself and
   refuses a document that tries to override them), a `pricesAsOf` missing while a row carries a
   `price`, or a malformed `pricesAsOf`/negative price.
2. The catalog **MUST** merge two scopes, nearest-wins by name: **built-in** (the documents
   shipped in the wheel — `anthropic`, `openai`, `google`, `openrouter`, `ai-gateway`, `groq`,
   `mistral`, `deepseek`, `xai`, `cerebras`, `together`, `local`, `ollama`, `lmstudio`) and
   **global** (`~/.docket/docket-providers.json`, `{"providers": {name: spec}}`, the operator's
   own registrations and overrides via `docket setup provider add`). `load_catalog()` **MUST**
   return the merged result; `Catalog.get(name)` and `Catalog.source_of(name)` (`"built-in"` /
   `"global"` / `""`) **MUST** read it. A document that fails validation is skipped when the
   catalog loads. A global write that leaves `presets`/`marketplace`/`credentialPrefix`/
   `pricesAsOf` unset **MUST** inherit each from a built-in of the same name (`save_provider`), so
   registering a local endpoint under a built-in's name does not erase presets or pricing the
   built-in still means.
3. `docket setup provider add <name> [<url>]` (options `--credential`, `--model`, `--ctx`,
   `--max-tokens`, `--no-preset`) **MUST** write a `ProviderSpec` to the global scope through
   `save_provider`, never to `fleet.json`, and audit it as `provider.add`. `<name>` is a path to
   a `kind: provider` file (registered as written), a catalog name (with no URL and no `--model`
   the catalog entry is registered as is), or a new name that **MUST** come with a URL
   (otherwise it fails naming the missing URL). A document built from a URL or `--model` over a
   catalog entry keeps every row the entry has, with its price, and the entry's auth, headers and
   identity fields; a `--model` the entry does not list adds a row. A new name has one row
   (`--model`, else `local-model`); it gets bearer auth with credential `<NAME>_API_KEY` when
   `--credential` is given, else `none` and `local: true`. Re-running with identical arguments **MUST** write
   nothing (idempotent; the output says `(unchanged)`). It also stores the provider's credential
   (flag, else its environment variable, else one already stored, else a hidden prompt on a
   terminal, else it fails naming the variable; api-keys.spec.md), probes `<baseUrl>/models` with
   it, and — unless `--no-preset` — applies the provider's preset (the one named like the
   provider, else its first catalog preset; or, for a provider with none, points every role and
   the default at its first model) and prints which role resolves to what. `--no-preset` writes
   no role row. The role table is the fleet's, so a preset can move members of every pod: when it
   moves any, `add` **MUST** print each pod with each moved role's model before and after, and the
   `--no-preset` command that would have left them alone. `setup model set`, `preset` and `reset`
   print the same per-pod lines without the hint. `docket setup provider remove <name>` deletes
   the global document and its stored credential (audited `provider.remove`).
4. Only the built-in and global scopes are read; a `providers` block left in `fleet.json` is
   ignored.
5. `resolve_endpoint` **MUST** resolve a catalog entry's base URL and exact model row directly
   from the document, and its credential through `resolve_credential`. A provider absent from the
   catalog **MUST** fall back to "Hosted gateway resolution" unchanged. `client_for` **MUST**
   dispatch on the entry's `dialect` over a closed adapter table and return `None` for a dialect
   with no adapter.
6. `resolve_endpoint` **MUST** carry a catalog entry's `auth.type`, `auth.header` and `headers`
   onto the resulting `Endpoint` (`auth_type`, `auth_header`, `headers`). The adapter
   **MUST** send `Authorization: Bearer <credential>` only for `auth_type: bearer` with a
   resolved credential, `<auth_header>: <credential>` only for `auth_type: header` with a resolved
   credential, and no credential header at all for `auth_type: none` or an unresolved credential —
   then append `headers` verbatim. This covers Azure OpenAI's `api-key` header and a
   multi-workspace Anthropic key's `anthropic-workspace-id` without a second adapter (ADR 0011).
   A `bearer`-auth document's request headers **MUST** stay byte-identical to a provider absent
   from the catalog. The `/models` probe sends the same headers.
7. **Observability.** `docket pod show <member> --json` **MUST** report, for the agent's
   resolved model, the provider's name, catalog scope (`"built-in"` / `"global"` / `""` when the
   provider is absent from the catalog), `dialect`, `baseUrl`, the resolved credential's name and
   source (`resolve_credential`'s `"override"`/`"env"`/`"store"`/`"none"`), and the
   model's `id`/`contextWindow`/`maxTokens` as resolved by requirement 9, with a `source` of
   `"declared"`, `"observed"` or `"unknown"` (plus `contextWindowSource`/`maxTokensSource` per
   limit and `observedAt`) — never a credential value. The human-readable render
   **MUST** show the same provider name, scope and credential source under the model line.
   `docket setup` **MUST** report each global provider document in `docket-providers.json` that
   fails the validation `ProviderSpec` applies — naming the file, the provider's name and the
   failing field — the same way a malformed pod `roles.json` overlay entry is named, and carry
   the same list under `--json` (`providerCatalog`).
8. **Prompt-cache markers.** For a model whose id, after any `<vendor>/` prefix, starts with
   `claude` (the `anthropic` provider and `anthropic/...` through a gateway),
   `build_payload` **MUST** encode the system message's `content` (when the first message is a
   system message) and the last message's `content` (a `tool` message included) as one text part
   `[{"type": "text", "text": <content>, "cache_control": {"type": "ephemeral"}}]`; a message whose
   content is empty or null (an assistant turn that only calls tools) **MUST** be left unmarked,
   because the provider refuses a marker on an empty text block, and a single message that is both
   first and last carries one marker. For every other model the request body **MUST** be
   byte-identical to the unmarked encoding. `request_part_bytes` counts the encoded parts as
   sent. No catalog field decides this: the model id does.
9. **Limits come from the provider.** A model's context window and output cap are resolved per
   limit as **declared > observed > unknown**. *Declared* is the exact `models[]` row's
   `contextWindow`/`maxTokens` (from `setup provider add --ctx/--max-tokens` or a `kind: provider`
   document); *observed* is what the provider's own `/models` body published, recorded in
   `~/.docket/provider-models.json`
   (`{"providers": {<name>: {"observedAt": "YYYY-MM-DD", "models": {<id>: {"contextWindow": N|null,
   "maxTokens": N|null}}}}}`), read by `observed_limits` and written only by
   `record_observed_models`; *unknown* is `None`, never a filled-in number. `probe_models`
   **MUST** return each advertised id's limits (`ProbeResult.limits`), detecting the wire shape
   **per row by field presence**: window from `max_input_tokens` (Anthropic), `context_window`
   (gateway), `meta.n_ctx` (llama.cpp -- **never** `meta.n_ctx_train`) or `context_length`
   (OpenRouter), first present wins; output cap from `max_tokens` or
   `top_provider.max_completion_tokens`. A value that is absent, null, not an integer or not
   positive (the gateway publishes `0` for a non-language model) is unknown. The shipped
   documents **MUST NOT** declare a limit; `price`, `pricesAsOf` and `presets` stay.
   Observations are recorded by `register_provider` (so `setup provider add` records what its
   registration probe saw) and, once a day per provider whose catalog scope is `global` (never an
   unregistered built-in), by `refresh_observed_models_due`, which `docket start --dispatch`'s
   sweep calls. A probe that is not a 200 records nothing and never erases an earlier
   observation. `setup provider add --ctx/--max-tokens` have no numeric default: absent means
   "take what the probe observes, else unknown", a given value is declared on the row `--model`
   names, or on the only row when `--model` is absent; with no `--model` and not exactly one row
   `add` **MUST** refuse (exit 1) naming `--model`, registering nothing. `setup provider show`
   **MUST** print one row per model with `WINDOW` and `OUTPUT` columns, each as
   `<N> (declared)`, `<N> (observed <date>)` or `unknown`; `--json` carries `contextWindow`,
   `maxTokens`, `limitsSource` (`declared` when any limit is declared, else `observed` when any is
   observed, else `unknown`), `contextWindowSource`, `maxTokensSource` and `observedAt`.

### Pricing

1. Each built-in direct-provider model whose price Docket claims **MUST** have a `price` on its
   catalog row, in USD per million tokens (`input`/`output`/`cacheRead`/`cacheWrite`, `Price`),
   read through `price_for` and unpacked in that order by `estimate_cost_usd`. Marketplace
   gateway models are the explicit exception described in requirement 4.
2. A model without pricing **MUST** report `n/a` (never $0.00) in cost output.
3. A model whose provider the catalog marks `local: true` (`is_local_provider`) **MUST** report
   `$0 (local)` — this is the true cost, not a placeholder for missing data, and **MUST NOT** fall
   through to the generic `n/a` path.
4. A model routed through a provider the catalog marks `marketplace: true` (`is_marketplace`;
   `openrouter` or `ai-gateway` among the built-ins), whose row carries no `price` (the explicit
   `openrouter/openrouter/free` router priced at `$0.00` is the one exception), **MUST** report a
   distinct, informative label (`n/a (bring your own)`) rather than the plain `n/a` used for an
   ordinary uncatalogued model — docket does not invent a number for pricing that changes per
   model/account.

## Interface Contracts

### CLI Command Signatures

```bash
docket setup model                              # Show the role→model policy (same as `model list`)
docket setup model list [--json]
docket setup model set <role|default> <provider/model>
docket setup model preset [<name>]              # No name: list the presets
docket setup model reset [--yes]                # Restore built-in defaults (asks to confirm)
docket setup provider add <name> [<url>] [--credential KEY] [--model ID] [--ctx N] [--max-tokens N] [--no-preset]
docket setup provider list|show|remove|export|rotate
docket pod show [<member>]                      # Each member's model and where it comes from
```

`docket setup model reset` with no registry file reports that no overrides exist and exits 0;
declining the confirmation exits 0 without changes.

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

The role set above is `ALL_ROLES`, keyed identically to `ROLE_CLASS`. A `docket-models.json`
`roles:` key that is not one of these names is ignored at read time and reported by
`docket setup`; nothing rewrites the file. A pod-scoped archetype with no row resolves per
requirement 5.

### Built-in Anthropic prices (USD per MTok)

| Class | Model | Input | Output |
| ----- | ----- | ----- | ------ |
| cheap | claude-haiku-4-5 | 0.80 | 4.00 |
| strong | claude-sonnet-4-6 | 3.00 | 15.00 |
| (premium anchor) | claude-opus-4-6 | 15.00 | 75.00 |

Prices are the `price` fields of the built-in provider documents, a manual snapshot dated by each
document's `pricesAsOf`, used for display and comparative estimates only — recorded spend comes
from measured token counts in docket's own per-session storage (see cost-tracking.spec.md). There
is no user pricing overlay. Providers marked `local: true` (the built-ins `local`, `ollama`,
`lmstudio`) price at `$0 (local)` regardless of whether the specific model id is catalogued, and
`openrouter/openrouter/free` carries an explicit zero price (the router contract, not a dated
selection of free models). Paid OpenRouter and AI Gateway preset models are deliberately left
unpriced — gateways can route and re-price by provider/account — and report
`n/a (bring your own)` instead.

### Registry file shape (current)

```json
{
  "default": "anthropic/claude-sonnet-4-6",
  "roles":       { "implementer": "openai/gpt-4.1" },
  "rankAnchors": { "standard": "openai/gpt-4.1-mini" }
}
```

`default`, `roles`, and `rankAnchors` are the only keys `load_registry` reads; any other key is
ignored.

### Return Codes

Like every other docket command (see cli-interface.spec.md), `docket setup model` uses a plain
success/failure contract — `0` on success, `1` on any error (invalid model, unknown role). There is no distinct exit code per error kind.

## Examples

### Viewing and changing the policy

```bash
$ docket setup model
Role to model policy
ROLE         MODEL                        PRICE         SOURCE   WHY
lead         anthropic/claude-haiku-4-5   $0.80/$4.00   builtin  orchestrates the pod; never edits code
implementer  anthropic/claude-sonnet-4-6  $3.00/$15.00  builtin  writes code in the project workspace
...
default  anthropic/claude-sonnet-4-6
rank anchors  anthropic/claude-opus-4-6 -> anthropic/claude-sonnet-4-6 -> anthropic/claude-haiku-4-5
PRICE is an estimate from a snapshot, not recorded spend
Change: docket setup model set <role|default> <provider/model>

$ docket setup model set implementer openai/gpt-4.1
ok implementer -> openai/gpt-4.1
! Moved 1 agent(s) in 1 pod(s) to the new role models:
  pod shop: implementer anthropic/claude-sonnet-4-6 -> openai/gpt-4.1
-> Next: docket setup
```

The moved lines are printed only when at least one agent changed; `reapply_role_policy` returns
one `RoleRepoint` (agent, pod, role, before, after) per moved agent.

### Switching the whole fleet to a free/local preset

```bash
$ docket setup model preset local
ok Preset local applied
  lead reviewer tester analyst writer monitor -> local/qwen3-30b-a3b
  implementer researcher critic operator -> local/qwen3-30b-a3b
  cost -> free per-token
  note -> Local OpenAI-compatible endpoint (llama.cpp/LM Studio/vLLM/Ollama) — no API key, ...
ok Registered local endpoint selected; no API key needed.
-> Next: docket setup

$ docket setup model
ROLE         MODEL                PRICE       SOURCE  WHY
lead         local/qwen3-30b-a3b  $0 (local)  user    orchestrates the pod; never edits code
...
default  local/qwen3-30b-a3b
rank anchors  local/qwen3-30b-a3b -> local/qwen3-30b-a3b -> local/qwen3-30b-a3b
```

## Validation

### Pre-conditions

- The key of `docket setup model set` **MUST** be one of the ten roles or `default`, and the model
  a well-formed `provider/model` id.

### Post-conditions

- After a role-row change, a preset or a reset, `.docket-meta.json` `model` **MUST** reflect the
  new value — the only place a model lives; `fleet.json`'s agent entries track bare registration
  only, never a copy of `model`.

### Invariants

- A role **MUST** always resolve to exactly one model id.
- Pricing **MUST** exist for every built-in model that Docket displays with a numeric price;
  marketplace routes may use the explicit unpriced label above.

## Implementation

Where the names above live today (the only place paths appear):

- `src/docket/models/selection.py`: `ALL_ROLES`, `ROLE_CLASS`, `REPO_AGENT_ROLE`,
  `rank_anchors`, `presets`, `preset_table`, `known_presets`, `load_registry`,
  `find_registry_problems`, `write_registry`, `resolve_role_model`, `resolve_step_model`,
  `validate_model`, `role_why`, `reapply_role_policy`, `RoleRepoint`, `is_local_provider`,
  `is_marketplace`, `price_for`, `prices_as_of`, `pricing_label`
- `src/docket/models/catalog.py`: `ProviderSpec`, `load_provider_document`, `load_catalog`,
  `Catalog`, `rank_anchors_of`, `check_rank_anchors`, `save_provider`, `delete_provider`, `remove_provider`, `export_provider`,
  `resolve_credential`, `resolve_limits`, `observed_limits`, `record_observed_models`,
  `refresh_observed_models_due`, `verify_endpoint`, `probe_spec`, `register_provider`,
  `model_readiness`
- `src/docket/teams/roles.py`: `BUILTIN_ARCHETYPES`, `STARTER_ARCHETYPES`, `load_registry`
  (`model_class`)
- `src/docket/teams/utils.py`: `estimate_cost_usd`, `project_ids`
- `src/docket/agent/llm.py`: `Endpoint`
- `src/docket/teams/fleet.py`: `set_model_both`
- `src/docket/teams/report.py`: the `docket pod show <member> --json` report
- `src/docket/core/dispatch.py`, `src/docket/teams/config_docs.py`: step-model resolution at a hop
  and in `docket pod validate`
- `src/docket/models/adapters/openai_http.py`: `resolve_endpoint`, `endpoint_from_spec`, `client_for`,
  `build_payload`, `request_part_bytes`, `probe_models`, `ProbeResult`, the chat client's header
  and response handling
- `src/docket/interfaces/cli/commands/setup_model.py`: `docket setup model` and `docket setup provider`
- `src/docket/interfaces/cli/commands/setup.py`, `src/docket/interfaces/cli/commands/setup_check.py`: the first-run report and the
  registry and provider-catalog checks
- `src/docket/interfaces/cli/commands/pod_show.py`: the `docket pod show` render
- `src/docket/serve.py`: the sweep that calls `refresh_observed_models_due`
- `src/docket/kernel/home.py`: the `Home` members `default_model`, `model_registry_file`,
  `providers_file`, `provider_models_file`
- `src/docket/kernel/templates.py`: `PROVIDER_TEMPLATES_DIR`
- `src/docket/models/document_fields.py`: `check_name`, `check_http_url`, `check_credential_name`, `reject_reserved_headers`
- `src/docket/templates/providers/*.yaml`: the built-in provider documents (prices, presets)
