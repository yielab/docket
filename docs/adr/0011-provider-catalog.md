# ADR 0011 (D-45): the provider catalog — model providers as configuration

**Question:** Docket's model wire has a clean port (`core/llm.py`) and one adapter
(`edges/adapters/llm.py`), but *which providers exist* lives in seven Python tables with no single
owner, the three direct presets (`anthropic`, `openai`, `google`) cannot be activated through the
CLI, a provider block holds one model and is replaced by the next `add`, and adding a provider of
record means editing six places. The 2026-09-26 request: make provider selection configurable the
way roles, policies and pipelines already are (a YAML document), with the abstractions that make
the agnosticism structural, robust and easy to extend — without overengineering. What is the shape,
and what earns a card?

**Where decided:** 2026-09-26, as Phase 29. **Activation gate:** none on Phases 27/28 (disjoint
files); the integrator confirms batching from function-level contention as usual.

**Evidence** (read at `0764091`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| Seven provider tables, seven populations: 2 built-in URLs, 5 credentials, 7 presets, 3 local prefixes, 9 in doctor, 4 key prefixes, 5 in the `keys setup` wizard | `edges/adapters/llm.py::_HOSTED_GATEWAY_BASE_URLS`; `core/provider.py::PROVIDER_CREDENTIAL_NAMES`; `core/models_policy.py::KNOWN_PRESETS`, `::PRESET_TABLE`, `::LOCAL_PROVIDERS`, `::MODEL_PRICING`; `cli/_doctor.py::_PROVIDER_KEY`; `cli/_keys.py::_KEY_PREFIXES`, `::_keys_setup` |
| The direct presets are unreachable through the CLI (deterministic reproduction) | `cli/__init__.py::_cmd_models_preset` requires `get_local_provider(preset)`; `core/provider.py::ping_endpoint` GETs `<base>/models` with no credential and `urllib.error.HTTPError` is a `URLError`, so 401 (api.anthropic.com, api.openai.com) and 404 (generativelanguage.googleapis.com `/v1beta/openai`) register as "unreachable"; no bypass flag exists. Measured 2026-09-26 with `curl` and `ping_endpoint` |
| The only escapes are hand-editing `fleet.json` or the process-wide `DOCKET_LLM_BASE_URL`, which drops registered limits | `edges/adapters/llm.py::resolve_endpoint`, precedence 1 |
| One model per block; a second `add` replaces the block | `core/fleet.py::add_local_provider`; `docs/MODEL-GATEWAYS.md` ("multi-model catalog import is not implemented") |
| `api: "openai-completions"` is written and read by nothing | model-profiles spec "Provider registration display fields" rule 2 |
| The port was designed for a second dialect without a second port | `core/llm.py` module docstring ("keeping a future second endpoint dialect from leaking wire fields into `core/`") |
| `Retry-After` is ignored; backoff is linear 2 s × attempt, 2 retries | `core/dispatch.py` hop retry loop (`ctx.do_sleep(_cfg.DISPATCH_RETRY_BACKOFF_S * attempt)`); `docs/MODEL-GATEWAYS.md` admits it |
| Precedent: a global catalog with credentials and per-entry operator assertions | `core/mcp_tools.py::McpServerConfig`, ADR 0009 §"MCP" |
| Precedent: YAML in, docket-owned JSON stored, YAML out | `core/archetypes.py::parse_yaml_file` → `docket-roles.json`; P27-7 `export` |
| Precedent: one-shot migration of a fleet field into its registry | model-profiles spec "The default model (single source)" rule 2 |
| `docket auth` is a stub that only reports "gone, use `docket keys`" | `cli/_keys.py::run_auth`; `tests/integration/test_provider_agnosticism.py::TestAuthProviderGoneHonestly` |
| Vendor facts used for the built-in documents | Anthropic "OpenAI SDK compatibility" (base `https://api.anthropic.com/v1`, tools supported, *"intended to test and compare … not a long-term or production-ready solution"*, no prompt caching, `strict` ignored, `prompt_tokens_details` always empty); Gemini "OpenAI compatibility" (base `https://generativelanguage.googleapis.com/v1beta/openai`, function calling, beta) — both read 2026-09-26 |

The trigger is an explicit scoped request plus a deterministic regression; no quantitative
threshold is invented. Full audit: `internal-docs/llm-provider-audit-2026-09-26.es.md` (gitignored).

## Decision

**A provider catalog of `kind: provider` documents in two scopes (built-in, global), from which
every table derives; a closed `dialect` field with one value that selects the adapter; credentials
referenced by name and never by value; and a registration that verifies with the credential instead
of without it.** Wiring over the port that exists; no plugin system, no second adapter until a
named trigger fires.

### 1. The document

The fifth `kind` of ADR 0010's envelope (YAML, camelCase, `kind` + `name`). Until P28-1 ships,
`core/provider.py::load_provider_document` checks `kind` itself; P28-1 then adds one `case
"provider"` that delegates to it.

```yaml
kind: provider
name: anthropic
dialect: openai-chat                # closed enum, one value today; selects the adapter
baseUrl: https://api.anthropic.com/v1
auth:
  type: bearer                      # bearer | header | none
  credentials: [ANTHROPIC_API_KEY]  # NAMES resolved from env or `docket keys`; first present wins
local: false                        # true = $0 pricing, no credential expected
marketplace: false                  # true = per-model prices are not tracked ("n/a (bring your own)")
credentialPrefix: sk-ant-           # optional; `docket keys validate` format hint
pricesAsOf: 2026-06-11              # required when any model carries a price
models:                             # catalog rows; `id` is what goes on the wire
  - id: claude-sonnet-4-6
    contextWindow: 200000
    maxTokens: 64000
    price: {input: 3.00, output: 15.00, cacheRead: 0.30, cacheWrite: 3.75}   # USD per MTok
presets:                            # what PRESET_TABLE holds today, attached to its provider
  - name: anthropic
    ranks: {economy: claude-haiku-4-5, standard: claude-sonnet-4-6, premium: claude-opus-4-6}
    note: >
      Anthropic's OpenAI-compatibility layer. Anthropic documents it as intended to test and
      compare models, not as a production solution: no prompt caching, `strict` ignored,
      system messages concatenated. For Claude with caching, a native dialect is a deferred item.
note: ""
```

A local provider, the way `provider add` writes it today but readable:

```yaml
kind: provider
name: local
dialect: openai-chat
baseUrl: http://127.0.0.1:8081/v1
auth: {type: none}
local: true
models:
  - {id: /mnt/data/models/qwen.gguf, contextWindow: 16384, maxTokens: 8192}
```

**Format rules.** `dialect` and `auth.type` are closed enums; an unknown value refuses the load
naming file, field and valid values. `auth.type: header` requires `auth.header`. A credential is a
name matching `^[A-Z][A-Z0-9_]*$`; a value never appears in a document, so a document can be
committed. `headers` (static extra request headers, added by P29-4) may not name `Authorization`,
`Content-Type` or `Accept`. `models` may be empty: any `provider/<id>` then resolves with `None`
limits, exactly as an unregistered id does today; an exact row supplies limits and price. A
provider with no `presets` is not a preset but is selectable with `docket models set`. `local:
true` implies `$0 (local)` pricing and `auth.type: none` by default. No `include`, inheritance,
variables or expressions (ADR 0010's cuts apply).

**The document grows one field per reader, never ahead of it** (ADR 0008 contract property 3).
P29-1 defines `name`, `dialect`, `baseUrl`, `auth{type: bearer|none, credentials}`, `local`,
`models[]{id, contextWindow, maxTokens}`, `note`. P29-2 adds `presets`, `marketplace`,
`credentialPrefix`, `price`, `pricesAsOf` with their consumers. P29-4 adds `auth.type: header`,
`auth.header`, `headers` with the wire that sends them.

### 2. Scopes, resolution, storage

| Scope | Holds | Lives in | Changed by |
| --- | --- | --- | --- |
| **Built-in** | the providers docket knows: `anthropic`, `openai`, `google`, `openrouter`, `ai-gateway`, `groq`, `mistral`, `deepseek`, `xai`, `cerebras`, `together`, `ollama`, `lmstudio`, `local` (the shipped default URL) | `src/docket/templates/providers/*.yaml`, in the wheel like `templates/policies/` | a release |
| **Global** | the operator's: local servers, own gateways, and **overrides** of a built-in by name (another URL, limits, credential) | `~/.docket/docket-providers.json`, docket-owned through `edges/store.py` | `docket models provider add` / `remove` |
| **Pod** | — | — | **deferred**: role policy plus pins already select the model; credentials are global like the MCP catalog |

**Resolution** is nearest-wins by name, global → built-in: the role-overlay rule one level shorter.
`resolve_endpoint(model)` becomes: split `provider/model` → catalog entry → exact model row if any →
credential by name → `Endpoint`. `DOCKET_LLM_BASE_URL` / `DOCKET_LLM_API_KEY` keep overriding
everything (model-profiles "Hosted gateway resolution" rule 4, unchanged). Credential precedence
becomes `DOCKET_LLM_API_KEY` → env `<name>` → central store `<name>`, for each name in
`auth.credentials` in order; the "non-placeholder key in the provider block" step disappears
because a document never holds a value.

**Storage and migration.** `fleet.json → providers` is ported **once** into
`docket-providers.json` on first catalog read and the fleet field is cleared — the pattern of
`profiles:` → `roles:` and `defaults.model` → registry `default`. `apiKey: "local"` or empty →
`auth: {type: none}`; a loopback URL or all-zero `cost` → `local: true`; a literal non-placeholder
`apiKey` value is moved into the central store under `<NAME>_API_KEY` and referenced by name, and
that move is audited (`provider.migrate`); `api`, `name`, `reasoning`, `input` are dropped (spec:
display-only). Destination is written before the source is cleared. `FleetConfig.providers` stays
one release for that read and is then removed (deferred, like ADR 0010's pre-`kind` format).

**One source for seven tables.** After P29-2 no module outside `core/provider.py` holds a
provider-name literal. Base URLs, credential names, presets, rank anchors, local prefixes,
marketplace labels, prices and key prefixes are functions over the loaded catalog (functions, not
import-time constants, because global scope changes at runtime). `config.DEFAULT_MODEL` remains
the one literal, pinned by a test to equal the built-in `anthropic` preset's `standard` rank.

### 3. The adapter seam: structural agnosticism without a second adapter

- `client_for(model)` dispatches on `dialect` over a closed dict in `edges/adapters/`:
  `{"openai-chat": OpenAIChatClient}`. A dialect is a file in `edges/adapters/` and a release —
  never a plugin, entry point or import by convention. It is `load_document`'s closed `match`
  applied to the wire.
- `OpenAIChatClient._headers()` reads `auth` (`bearer` → `Authorization: Bearer`; `header` →
  `<auth.header>: <value>`; `none` → nothing) and appends `headers`. This covers Azure OpenAI's
  `api-key` header and Anthropic's `anthropic-workspace-id` without vendor code. Azure's
  `api-version` query parameter stays deferred.
- `core/llm.py` keeps its port. `Endpoint` gains typed `auth_type`, `auth_header`, `headers` and
  loses `is_local` (no consumer). No new dependency: `urllib` + `pyyaml` (already required).
- **Why not an Anthropic Messages adapter now.** It would buy prompt caching (cache read ≈ 10 %
  of input price), structured outputs and thinking output. Trigger: a hosted Anthropic fleet whose
  measured `usage` is mostly repeated prefix, or an operator asking twice. Today: zero hosted use
  in this system, and D-18 bans per-vendor clients. `dialect` leaves the slot; that is the whole
  commitment. D-42's "cut: a second dialect" stands — this ADR adds a closed field with one value.

### 4. Registration, verification, CLI

`docket models provider add` verifies **with the resolved credential** and classifies the result
instead of collapsing it to a boolean; the HTTP probe moves to `edges/adapters/llm.py::probe_models`
(side effects belong in `edges/`), the classification stays pure in `core/provider.py`:

| `GET {baseUrl}/models` with credential | Action |
| --- | --- |
| connection refused, DNS, timeout | **refuse** registration (today's behaviour; the existing fail-closed test stays) |
| 200 | register; ids the response advertises and `models[]` lacks are printed as a suggestion, never written |
| 401 / 403 | register with a **warning** naming the missing or rejected credential; `docket init` still stops at readiness until it exists |
| 404 on `/models` | register with the warning "no /models route; capability not verified" |
| other 4xx / 5xx | register with a warning carrying the status |

No `--no-verify`: the classification makes it unnecessary.

CLI surface, all under the existing `docket models provider`:

```text
docket models provider add <file.yaml>                      # a kind: provider document
docket models provider add <name> <base-url> --model <id> [--ctx N] [--max-tokens N] [--credential NAME]
                                                            # today's shortcut; it produces the same document
docket models provider list                                 # name, scope, dialect, baseUrl, credential present
docket models provider show <name> [--json]                 # resolved entry with its scope
docket models provider remove <name>                        # global scope only; removing an override restores the built-in
docket models provider export <name> [<file>]               # the §1 document
```

`docket models preset <name>` lists every preset the catalog carries and no longer demands a
registered block for `anthropic`/`openai`/`google`: the URL is built in, and what is required is the
credential (readiness). `docket config explain <agent>` gains a `provider` section (name, scope,
dialect, base URL, credential source `override|env|store|none`, exact-row limits). `docket doctor`
reads the catalog for key coverage and reports a malformed global document as it reports a
malformed role overlay.

`docket auth` (a stub whose every subcommand answers "gone, use `docket keys`") becomes an entry in
`__main__.py::_REMOVED`, the mechanism the project uses for `workflow`, `team` and `eval`; `docket
keys setup` iterates the catalog's built-in credentials instead of its own five-row table.

**Retries.** The adapter reads `Retry-After` (seconds or HTTP-date) on a retryable status into
`ChatResponse.retry_after_s`, threaded through `AgentLoopResult` and `TurnResult`; the hop retry
loop sleeps `min(max(linear, retryAfter), DISPATCH_RETRY_MAX_WAIT_S)` (new constant, default 60 s).
Retry counts and the `FailureKind` vocabulary do not change. This is a gap in the retry path that
already exists — not a new capability — and it becomes reachable the moment hosted providers do.
It is the one card the integrator may hold back for an observed 429 without affecting the others.

## Rules this ADR amends (so no two documents disagree)

| Document, rule | Today | After |
| --- | --- | --- |
| model-profiles "Provider readiness" 2 | "A direct Anthropic, OpenAI, or Google key without an explicitly registered compatible base URL MUST NOT satisfy readiness" | "A selected model is ready when its provider resolves in the catalog (built-in or global) to a base URL and every credential the entry requires is present. A built-in hosted provider needs only its credential." (P29-2) |
| model-profiles "Provider readiness" 3 | "Registration MUST verify `<base-url>/models` before writing provider state; an unreachable endpoint returns failure" | "Registration MUST probe `<base-url>/models` with the resolved credential and classify (§4 table); only a transport failure refuses; every HTTP status registers, with a warning when it is not 200." (P29-3) |
| model-profiles "Hosted gateway resolution" 2 | built-in URLs are `openrouter` and `ai-gateway` | built-in URLs are those of the shipped `templates/providers/*.yaml`, listed in the spec (P29-2) |
| model-profiles "Hosted gateway resolution" 3 | credential precedence includes "a non-placeholder key in the exact registered provider block" | that step is removed; a document holds names only (P29-1) |
| model-profiles "Provider registration display fields" | `api`, `name`, `cost`, `reasoning`, `input` are display-only fields of the block | section removed; the fields no longer exist after migration (P29-1) |
| model-profiles "Presets" 1 | the built-in presets MUST include the seven names | the built-in presets are those the built-in documents declare, and the seven names stay among them (P29-2) |
| model-profiles "Pricing" 1, 3, 4 | keyed to `MODEL_PRICING`, `LOCAL_PROVIDERS`, the marketplace tuple | keyed to catalog rows, `local: true`, `marketplace: true` (P29-2) |
| api-keys "Propagation" 3 | "…require an explicitly registered OpenAI-compatible endpoint until Docket ships a native adapter" | "…are sufficient for a built-in hosted provider; readiness is the catalog's base URL plus the credential" (P29-2) |
| api-keys `setup` | interactive wizard over a fixed list | wizard over the catalog's built-in credentials (P29-7) |
| cli-interface `docket models` | `provider add <name> <base-url> …` only; `preset` for `anthropic`, `openai`, `google` requires a registered block | five `provider` actions; `preset` requires nothing beyond the catalog (P29-3) |
| cli-interface `docket auth` | a section with four subcommands | removed; listed with the removed commands (P29-7) |
| pod-dispatch "Retries" | linear backoff only | `Retry-After` honoured with a ceiling (P29-5) |
| ADR 0010 §1 | "Four kinds" | five, `provider` delegating to `core/provider.py` (amended in place) |

Rules that **stand** and were checked: D-18 (no per-vendor clients — a closed dialect map is one
client per open protocol); D-24/D-25 (no streaming, no LiteLLM, no gateway of our own); D-42's cut
of a second dialect; ADR 0009's "no second file format, no loader framework" (the document is the
same YAML, and the loader is one function); README "Compatible HTTP, not provider SDK parity";
model-profiles "Hosted gateway resolution" 1 and 4; the standing no-fabricated-dollar-figures rule
(prices move, they do not change meaning).

## Code this ADR retires (no legacy left behind)

| Symbol | Card | Replacement |
| --- | --- | --- |
| `core/fleet.py::add_local_provider`, `::get_local_provider` | P29-1 | `core/provider.py::save_provider`, `::load_catalog` |
| `core/provider.py::local_provider_config`, `::register_local_provider`, `::ProviderRegistration`, `::ping_endpoint`, `::DEFAULT_MODEL_NAME`, `::DEFAULT_*` provider constants | P29-3 (`ping_endpoint` → `edges/adapters/llm.py::probe_models`) | `register_provider`, `verify_endpoint`, `ProviderVerification`, the built-in `local.yaml` |
| `edges/adapters/llm.py::_HOSTED_GATEWAY_BASE_URLS`; `core/provider.py::PROVIDER_CREDENTIAL_NAMES` | P29-2 | catalog functions |
| `core/models_policy.py::KNOWN_PRESETS`, `::PRESET_TABLE`, `::LOCAL_PROVIDERS`, `::UNPRICED_MARKETPLACE_PROVIDERS`, `::MODEL_PRICING`, `::MODEL_PRICING_AS_OF`, `::_RANK_ANCHORS` literal | P29-2 | `presets()`, `is_local_provider()`, `price_for()`, `rank_anchors()` over the catalog |
| `cli/_doctor.py::_PROVIDER_KEY`; `cli/_keys.py::_KEY_PREFIXES`; `scripts/gen_cli_docs.py::_provider_credential_names` literal source | P29-2 | catalog |
| `core/llm.py::Endpoint.is_local` | P29-4 | `local` on the document |
| `cli/_keys.py::run_auth` and helpers, the `auth` command, `::_keys_setup` provider tuple | P29-7 | `__main__._REMOVED["auth"]`; the catalog |
| `FleetConfig.providers` | deferred one release | removed after the migration has had a release to run |

## Verdict table

| Item | Verdict | Card | Reason |
| --- | --- | --- | --- |
| `kind: provider` document, loader, `docket-providers.json`, one-shot migration, `dialect` dispatch | **DO** | P29-1 | foundation; byte-identical resolution for today's configs |
| Built-in documents; every table derived; direct presets reachable | **DO** | P29-2 | one owner; closes the regression on the preset side |
| Verification with credential and classification; `add <file>`, `list`, `show`, `remove`, `export`; probe in `edges/` | **DO** | P29-3 | closes the regression on the registration side; fixes the side-effect-in-core smell |
| `auth.type: header` + `headers` on the wire | **DO** | P29-4 | Azure/workspace headers without vendor code |
| `Retry-After` with a ceiling | **DO** (removable) | P29-5 | see §4 |
| `config explain` provider section, doctor, docs, spec | **DO** | P29-6 | contract property 5 |
| Retire `docket auth`; `keys setup` over the catalog | **DO** | P29-7 | the seventh table, and a command that only says it is gone |
| A second dialect (Anthropic Messages, Bedrock `converse`, Responses API) | **DEFER** | — | **Trigger:** hosted Anthropic usage whose measured input is mostly repeated prefix, or an operator on Bedrock/Vertex, asked twice |
| Azure `api-version` query | **DEFER** | — | **Trigger:** an operator on Azure OpenAI |
| Catalog and price discovery from `/models` | **DEFER** | — | P29-3 only suggests ids. **Trigger:** a built-in `pricesAsOf` older than six months and one figure shown false |
| Pod-scoped providers, model per step | **DEFER** (unchanged) | — | ADR 0009's triggers |
| Removing `FleetConfig.providers` | **DEFER** | — | one release after Phase 29 ships |
| Automatic fallback to another model or provider | **CUT** | — | governance: it would change which model ran code without approval; rank anchors stay "not a fallback chain" |
| Streaming, LiteLLM or an own gateway, vendor SDKs | **CUT** (unchanged) | — | D-18, D-24, D-25 |
| Adapter plugins or entry points; `include`, inheritance, variables in the document | **CUT** | — | a dialect is a release; YAML stays data (ADR 0010) |

## Test discipline

ADR 0009's rule: one RED behavioural test per card in the module's `SUBJECT` file; a negative case
only for fail-closed properties (P29-1: an unknown `dialect`/`auth.type` refuses the load; P29-3:
a transport failure still refuses registration). The three "same as before" oracles are existing
tests left untouched: `TestEndpointResolution`, `TestPricingHonesty`/`TestLocalPreset`/
`TestHostedGatewayPreset`, `TestHopRetryLoop`. P29-2 replaces `test_five_known_providers` with an
AST test in the same file asserting no provider-name literal outside `core/provider.py`. P29-3's
round trip (`export` → `add` on a fresh home → identical `show --json`) is the phase's integration
proof. Goldens change only where CLI surface changes (`help`, completions, `models preset`
listing) and each card lists the lines.

## Waves (proposed; the integrator confirms from function-level contention)

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 47 | P29-1 | `core/provider.py` (rewritten: model, loader, catalog, migration, `resolve_credential`), `config.py::PROVIDERS_FILE`, `core/fleet.py` (delete two functions; field comment), `edges/adapters/llm.py::resolve_endpoint` + `::client_for` only, one-line call swaps in `cli/__init__.py::_cmd_models_preset` and `cli/_agents.py` |
| 48 | P29-2 ∥ P29-5 ∥ P29-7 | `core/provider.py`: P29-2 owns the new derivation functions and the P29-2 fields; `core/models_policy.py`, `templates/providers/`, `cli/_doctor.py::_PROVIDER_KEY` users, `cli/_keys.py::_validate_key_format`, `scripts/gen_cli_docs.py` → P29-2; `core/llm.py::ChatResponse`, `edges/adapters/llm.py::complete` (the `HTTPError` branch only), `core/agent_loop.py::call_backend_and_handle_response` + `done`, `core/runtime_driver.py::TurnResult`, `edges/adapters/docket_runtime.py::run_turn` (the `TurnResult(...)` construction only), `core/dispatch.py` (the `do_sleep` line only), `config.py` → P29-5; `cli/_keys.py::_keys_setup` + `run_auth`, `cli/__init__.py` (the `auth` command only), `__main__.py::_REMOVED` → P29-7 |
| 49 | P29-3 ∥ P29-4, then P29-6 | `core/provider.py`: P29-3 owns `verify_endpoint`/`register_provider`/`remove_provider`/`export_provider`, P29-4 owns `AuthSpec` and the `headers` field; `edges/adapters/llm.py`: P29-3 owns new `probe_models`, P29-4 owns `_headers` + `core/llm.py::Endpoint`; `cli/_provider.py`, `cli/__init__.py` (`models provider` dispatch + `_cmd_models_preset`) → P29-3; `cli/_config.py`, `cli/_doctor.py` (own check function), `docs/` → P29-6 after both merge |

Pre-assigned spec versions (after Phase 28's): model-profiles 2.11.0 (P29-1), 2.12.0 (P29-2),
2.13.0 (P29-3), 2.14.0 (P29-4), 2.15.0 (P29-6); api-keys 1.5.0 (P29-2), 1.6.0 (P29-7);
pod-dispatch 6.18.0 (P29-5); cli-interface 1.40.0 (P29-3), 1.41.0 (P29-6), 1.42.0 (P29-7);
config-format 1.2.0 (P29-1, only if P28-1 has shipped by then; otherwise the integrator adds the
`provider` arm when merging P28-1). Version numbers stay unique even if Phase 29 lands before 28.

## Consequences

- The honest sentence after Phase 29: *a provider is a file you can read, commit and export; a
  hosted provider works with its key alone; a local server works with its URL alone; and adding
  a compatible provider of record is one YAML file.* Before it, the sentence stops at "two
  gateways work with a key; the rest need a hand-edited JSON".
- `fleet.json` holds agents, bindings and flags only; endpoints have their own registry like MCP
  servers do.
- The `dialect` field is a published contract like the harness envelope: its one value is pinned
  by test; a second value is a release note, never a silent addition.
- README limit "Compatible HTTP, not provider SDK parity" stays true and gains "and Anthropic's
  compatibility layer is documented by Anthropic as for evaluation"; the integrator rewrites that
  bullet in P29-6's merge (D-37).
