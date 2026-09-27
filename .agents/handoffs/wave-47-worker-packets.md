# Wave 47–49 worker packets — Phase 29, the provider catalog (D-45)

Coordinator: the session that planned Phase 29 on 2026-09-26; activated 2026-09-27 by the
integrator. **Base commit for Wave 47: the commit that opened it on `main`**
(`git log -1 --format=%h -- .agents/handoffs/wave-47-worker-packets.md`; Phase 28 closed at
`56e8d9d` just before it); Waves 48 and 49 rebase onto the rollup commit that closed the previous
wave. Corrections applied at activation, which override the card text where they differ:
`pod-dispatch.spec.md` is at 6.20.0 after Phase 28, so P29-5 takes **6.21.0**;
`config-format.spec.md` exists at 1.1.0, so P29-1 takes 1.2.0 and adds the `provider` arm to
`core/config_docs.py::load_document`; goldens are 19 cases. One card, one Sonnet worker, one isolated worktree each. Decision, the document, the two
scopes, the adapter seam, the amended rules and the retired-code table:
[docs/adr/0011-provider-catalog.md](../../docs/adr/0011-provider-catalog.md). The card
(`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P29-<N>`) is the contract; this
file is the map. Read §0 and your own packet only.

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 47 | P29-1 | — |
| 48 | P29-2, P29-5, P29-7 | P29-5, P29-7, P29-2 |
| 49 | P29-3 ∥ P29-4, then P29-6 | P29-4, P29-3, P29-6 |

## 0. Rules for every worker

- **Isolation.** One branch `p29-<N>-<slug>` in your own worktree. Never touch `~/.docket`: every
  CLI run sets `export W=$(mktemp -d) DOCKET_HOME=$W/.docket` (**never override `HOME`**: it
  breaks uv's cache). pytest isolates `DOCKET_HOME` through the autouse fixture in
  `tests/conftest.py`, which moves only the constants listed in `_DOCKET_HOME_PATHS` -- a card
  that adds a `DOCKET_HOME`-derived path to `config.py` registers it there in the same commit. **Never call a real model endpoint and never
  probe a real vendor host**; the deterministic HTTP fakes in `tests/integration/test_llm_port.py`
  (`_serve` / the `http.server` helpers) and `test_docket_driver.py` are the pattern.
- **Never `git stash`.** Set work aside with a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`: a worktree inherits the parent's
  `VIRTUAL_ENV` and it points at the wrong venv.
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Amend the
  spec requirement text and add the pre-assigned version + changelog line. 3. Write the RED test
  and see it fail on the base for the stated reason. 4. Smallest implementation. 5. Gates.
- **Test rule (ADR 0011).** One RED behavioural test in the module's existing `SUBJECT` file; a
  second only for the card's fail-closed negative case (P29-1, P29-3). Existing tests, goldens
  and specs are the no-change oracle. No agent-lane tests, no guards, no new test files unless
  the card names one.
- **The document grows one field per reader.** Add a `ProviderSpec` field only in the card that
  ships its consumer (P29-1 core fields; P29-2 presets/prices/marketplace/credentialPrefix;
  P29-4 `auth: header`/`headers`). A field with a validator and no reader is the unwired-machinery
  shape this repository keeps finding.
- **A credential value never enters a document, a fixture or an error message.** Documents carry
  names. Tests that need a key set it in `os.environ` or the isolated store.
- **Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never
  prints, never opens a socket (P29-3 moves the probe to `edges/`). Docket-owned JSON only through
  `edges/store.py`. Every tool call through `core/tools.py::dispatch_tool`.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `docs/` except `docs/commands.md`
  regeneration and, for P29-6 only, the four docs its card names. Return the README/CHANGELOG
  line you would add instead of writing it. Never edit `scripts/metrics.py` or
  `scripts/validate-specs.sh`. Never touch `core/pod.py`, `core/archetypes.py`, `core/policy.py`,
  `core/orchestrator.py` or `core/pod_apply.py`; `core/config_docs.py` is touched by P29-1 only
  (the `provider` arm of `load_document` and `KINDS`).
- **Goldens.** `bash tests/golden/run.sh verify-all` stays byte-identical unless your packet
  names a case; then regenerate only that case and list every changed line with its reason.
- **Worker gates** before returning:

  ```bash
  env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src
  env -u VIRTUAL_ENV uv run pytest -q
  bash tests/golden/run.sh verify-all
  bash scripts/validate-specs.sh
  env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check   # needs `click`: run `env -u VIRTUAL_ENV uv sync --extra mcp` once in your worktree first
  env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <every .py you touched>
  ```

  `scripts/metrics.py --check` is expected to fail on a branch that adds tests; say so.
- **Commit.** One commit per card. Subject `Type: description` (`Add:`/`Fix:`/`Docs:`), ASCII,
  body says what was false and what is now true. **No AI mention, no `Co-Authored-By` trailer of
  any kind.** Before committing: `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-'`
  prints nothing. Do not push, do not merge into `main`.
- **Return** a delta of 1,500–3,000 characters, no logs: card / branch / commit; outcome;
  user-visible behaviour; changed paths and owned functions; spec sections + one changelog line
  per spec; README/CHANGELOG line for the integrator; RED evidence (test id, base failure reason);
  focused tests -> result; worker gates -> pass or first failing gate; goldens changed;
  missing/failed; pending in this card; later follow-ups (locators only); contention note.

Symbols below were located at `0764091` and drift; re-locate every one with `rg -n` before editing.

## P29-1 — a provider is a document, and today's configuration resolves exactly as before

Branch `p29-1-provider-document`. Spec `specs/functional/model-profiles.spec.md` -> 2.11.0: add a
section "Provider catalog" (document fields this card consumes, the two scopes, nearest-wins,
`docket-providers.json`, the one-shot migration and what it does with a literal `apiKey`); amend
"Hosted gateway resolution" rule 3 (drop the provider-block-key step); delete "Provider
registration display fields" and fix the Scope paragraph that says `provider add` writes
`fleet.json`. `specs/functional/config-format.spec.md` -> 1.2.0: `provider` joins the kinds in
the Scope list and the dispatch rule, its parser is `core/provider.py::load_provider_document`,
and `docket validate <file>` accepts a provider document. Implementation of that last point:
`core/config_docs.py` adds `"provider"` to `KINDS` and one `elif effective_kind == "provider"`
arm in `load_document` that calls `load_provider_document` and maps `ProviderError` to
`ConfigDocError` the way the role arm maps `ArchetypeError` -- nothing else in that module.

- **Where.** `src/docket/core/provider.py` — rewrite. Keep the module docstring honest (it says
  "Local provider registration"). Model: `ProviderSpec`, `AuthSpec`, `ModelRow` (pydantic,
  `ConfigDict(populate_by_name=True)`, camelCase aliases like `core/pod.py::PodSettings`).
  Loader: `load_provider_document(path)`; errors: `ProviderError(file, field, message, valid)`
  (an `Exception` subclass with those attributes; `str()` renders `file: field: message (valid:
  a, b)`). Catalog: `Catalog` dataclass with `entries: dict[str, ProviderSpec]` and `scopes:
  dict[str, str]`; `load_catalog()`, `Catalog.get`, `Catalog.source_of`, `save_provider`,
  `delete_provider`. `resolve_credential(spec) -> (value, source)`. `migrate_fleet_providers()`.
  Built-in directory: `config.py` gets `PROVIDER_TEMPLATES_DIR = Path(__file__).parent /
  "templates" / "providers"` next to the policy templates constant (create the directory with a
  `.gitkeep`; P29-2 fills it). `config.py::PROVIDERS_FILE = DOCKET_HOME / "docket-providers.json"`
  next to `MCP_SERVERS_FILE`, **and** `("PROVIDERS_FILE", "docket-providers.json")` in
  `tests/conftest.py::_DOCKET_HOME_PATHS` so the autouse isolation moves it (P28-7 did the same
  for `PLUGINS_DIR`).
- **Fleet.** `src/docket/core/fleet.py`: delete `add_local_provider` and `get_local_provider`;
  leave `FleetConfig.providers` with a two-line comment: read once by `migrate_fleet_providers`,
  cleared afterwards, removal deferred one release (ADR 0011).
- **Adapter.** `src/docket/edges/adapters/llm.py::resolve_endpoint`: replace the
  `_fleet.get_local_provider(provider)` read with `load_catalog().get(provider)`; keep steps 1
  (env override) and 3 (`_HOSTED_GATEWAY_BASE_URLS`) and the derived `<PREFIX>_API_KEY` fallback
  byte-for-byte for a provider **absent** from the catalog — P29-2 retires them, not you. When the
  catalog has the provider: base URL from the document, limits from the exact row, key from
  `resolve_credential`. `client_for`: `_DIALECTS: dict[str, type[OpenAIChatClient]] =
  {"openai-chat": OpenAIChatClient}`; unknown -> `None`. `Endpoint` gains nothing in this card.
- **Call sites.** `src/docket/cli/__init__.py::_cmd_models_preset`: the `registered =
  _fleet.get_local_provider(preset) or {}` line becomes `registered = _prov.load_catalog().get(preset)`
  and the `models[0]` read below it uses `registered.models[0].id` — nothing else in that function.
  `src/docket/cli/_agents.py`: the `bool(fleet.providers)` foundation check reads
  `bool(load_catalog().scopes)` filtered to `"global"`.
- **Tests you own.** `tests/unit/core/test_provider.py` (RED + negative case; `SUBJECT =
  "docket.core.provider"`); `tests/integration/test_llm_port.py::TestEndpointResolution` — the
  nine `monkeypatch.setattr(_fleet, "get_local_provider", ...)` sites become a helper that writes
  a document into the isolated `docket-providers.json` (or monkeypatches `load_catalog`); the
  assertions stay identical. `tests/integration/test_install.py` and
  `test_maintain_rebuild.py` call `_fleet.add_local_provider(...)` — swap to `save_provider(ProviderSpec(...))`.
  `tests/integration/test_provider_registration.py` reads `fleet.json["providers"]` — read
  `docket-providers.json` instead; the assertions on the *shape* change to the document shape and
  you list them in the return. Fixture for the migration case: this machine's block redacted to
  `id: /models/qwen.gguf`, `baseUrl: http://127.0.0.1:8081/v1`, `contextWindow: 16384`,
  `maxTokens: 8192`, `apiKey: local`, `api: openai-completions`, plus the display fields.
- **RED.** `test_provider.py`: `from docket.core.provider import load_provider_document` — ImportError
  on the base. `test_llm_port.py`: after writing the fleet block and calling `resolve_endpoint`,
  `docket-providers.json` exists and equals the expected document — fails on the base (file never
  written).
- **Do not touch:** `_HOSTED_GATEWAY_BASE_URLS`, `PROVIDER_CREDENTIAL_NAMES` (P29-2 deletes them);
  `_headers`, `complete` (P29-4, P29-5); `cli/_provider.py` beyond keeping `register_local_provider`
  compiling (it now builds a `ProviderSpec` and calls `save_provider`; P29-3 rewrites it);
  `cli/_doctor.py`, `cli/_keys.py`.
- **Goldens:** none expected.

## P29-2 — the providers docket knows are documents, and every table derives from them

Branch `p29-2-builtin-providers`. Spec `model-profiles.spec.md` -> 2.12.0 ("Presets" 1: the
built-in presets are those the built-in documents declare and the seven names stay among them;
"Hosted gateway resolution" 2: built-in URLs are the shipped documents, list them; "Provider
readiness" 2: ready = catalog base URL + every required credential present, a built-in hosted
provider needs only its credential; "Pricing" 1/3/4: keyed to rows, `local: true`, `marketplace:
true`). `api-keys.spec.md` -> 1.5.0 ("Propagation" 3: the "until Docket ships a native adapter"
clause goes; a stored key is sufficient for a built-in hosted provider).

- **Fields (with readers in this card).** `ProviderSpec.presets: list[Preset]` (`Preset{name,
  ranks: dict[Literal["economy","standard","premium"], str], note: str}`; rank values are bare
  model ids, the provider prefix is implied), `marketplace: bool = False`, `credentialPrefix: str
  = ""`, `pricesAsOf: str = ""` (`^\d{4}-\d{2}-\d{2}$`, required if any row has `price`),
  `ModelRow.price: Price | None` (`Price{input, output, cacheRead, cacheWrite}` floats ≥ 0).
- **Templates.** `src/docket/templates/providers/<name>.yaml`, one per built-in (ADR 0011 §2 list).
  Copy today's values: `PRESET_TABLE` ranks and notes (strip the "requires a registered
  compatible endpoint" sentences — they become false in this card; keep the free-router
  experimental sentence), `MODEL_PRICING` rows under their provider, `MODEL_PRICING_AS_OF` as
  `pricesAsOf`, `LOCAL_PROVIDERS` as `local: true`, `UNPRICED_MARKETPLACE_PROVIDERS` as
  `marketplace: true`, `_KEY_PREFIXES` as `credentialPrefix`, `PROVIDER_CREDENTIAL_NAMES` as
  `auth.credentials`, `_HOSTED_GATEWAY_BASE_URLS` as `baseUrl`. New URLs: `anthropic`
  `https://api.anthropic.com/v1`, `openai` `https://api.openai.com/v1`, `google`
  `https://generativelanguage.googleapis.com/v1beta/openai`, `groq` `https://api.groq.com/openai/v1`,
  `mistral` `https://api.mistral.ai/v1`, `deepseek` `https://api.deepseek.com/v1`, `xai`
  `https://api.x.ai/v1`, `cerebras` `https://api.cerebras.ai/v1`, `together`
  `https://api.together.xyz/v1`, `ollama` `http://127.0.0.1:11434/v1`, `lmstudio`
  `http://127.0.0.1:1234/v1`, `local` = today's `core/provider.py::DEFAULT_BASE_URL`. Credentials
  for the four new hosted ones: `GROQ_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`,
  `CEREBRAS_API_KEY`, `TOGETHER_API_KEY`. No presets and no prices for those (nothing claims a
  figure that was not in the table). The `anthropic` and `google` preset notes carry the vendor
  wording quoted in the ADR evidence table (evaluation-only / beta). `pyproject.toml`: confirm the
  `templates/providers/*.yaml` files ship in the wheel the way `templates/policies/*.json` do
  (hatchling include list) and in `packages/docket-runtime/` if that build includes templates.
- **Derivations.** `core/models_policy.py`: `presets() -> list[tuple[provider, Preset]]`,
  `preset_table() -> dict[str, dict[str, str]]` (same keys as today's rows so
  `_cmd_models_preset` and `docket models` render unchanged), `known_presets()`,
  `is_local_provider(prefix)`, `is_marketplace(prefix)`, `price_for(model) -> tuple | None`,
  `prices_as_of(model) -> str`, `rank_anchors() -> dict` (= built-in `anthropic` preset ranks
  with the `anthropic/` prefix). Delete the constants they replace; update `pricing_label`,
  `validate_model`, `load_registry`, `find_registry_problems`, `write_registry`,
  `_init_role_overrides_from_tiers`, `core/utils.py::estimate_cost_usd`, and every `cli/__init__.py`
  reader of `KNOWN_PRESETS`/`PRESET_TABLE` (the presets listing, the "Preset:" footer line). The
  `PRICE column is an estimate from a snapshot (as of …)` footer reads `prices_as_of` of the
  models shown (one date when all agree, else "various").
- **Deletions.** `edges/adapters/llm.py::_HOSTED_GATEWAY_BASE_URLS` and the
  `PROVIDER_CREDENTIAL_NAMES` import (a provider absent from the catalog resolves only under
  `DOCKET_LLM_BASE_URL`, deriving `<PREFIX>_API_KEY`; else `None`); `core/provider.py::PROVIDER_CREDENTIAL_NAMES`
  (`model_readiness` reads the catalog); `cli/_doctor.py::_PROVIDER_KEY` (both readers use
  `load_catalog().get(prefix).auth.credentials[0]`); `cli/_keys.py::_KEY_PREFIXES`
  (`_validate_key_format` looks the name up across built-in documents' `credentialPrefix`);
  `scripts/gen_cli_docs.py::_provider_credential_names` iterates the catalog.
- **Tests you own.** `tests/unit/core/test_provider.py`: replace `test_five_known_providers` with
  (a) an AST test over `src/docket/**/*.py` minus `core/provider.py`: no `ast.Dict`/`ast.Tuple`
  literal whose string constants include `"anthropic"` or `"openai"` (fails on the base on
  `cli/_doctor.py::_PROVIDER_KEY`); (b) every file in `templates/providers/` loads; (c)
  `config.DEFAULT_MODEL == "anthropic/" + anthropic standard rank`. `tests/integration/test_provider_agnosticism.py`:
  `TestPricingHonesty`, `TestLocalPreset`, `TestHostedGatewayPreset`, `TestNonAnthropicPresetShowsNoResidue`
  must stay green **unedited**; if one references a deleted constant, swap only that reference and
  say so. `tests/integration/test_llm_port.py::TestEndpointResolution`: unedited.
- **Goldens:** `tests/golden/cases/readonly/help.golden` and any `models` case that prints the
  preset list may change by the added built-ins — list every line.
- **Do not touch:** `AuthSpec` (P29-4), `complete` (P29-5), `_keys_setup`/`run_auth` (P29-7),
  `cli/_provider.py` (P29-3).

## P29-5 — a retry waits as long as the provider asked, up to a ceiling

Branch `p29-5-retry-after`. Spec `specs/functional/pod-dispatch.spec.md` -> 6.21.0 (the base is
at 6.20.0; the card text's 6.18.0 predates Phase 28), section
"Retries and the failure-kind taxonomy": the sleep before retry N is
`min(max(DISPATCH_RETRY_BACKOFF_S × N, retryAfter), DISPATCH_RETRY_MAX_WAIT_S)`; `retryAfter` is
the endpoint's `Retry-After` on a retryable status, else 0.

- **Where.** `src/docket/core/llm.py::ChatResponse` add `retry_after_s: float | None = None`.
  `src/docket/edges/adapters/llm.py::complete`, the `except urllib.error.HTTPError` branch only:
  `_retry_after_seconds(ex.headers)` (module-private; integer seconds, or `email.utils.parsedate_to_datetime`
  minus now, clamped ≥ 0; `None` when absent/unparseable) set only when
  `_classify_http_status(ex.code) == "daemon_error"`. `src/docket/core/agent_loop.py`:
  `AgentLoopResult` gains `retry_after_s: float | None = None`; `call_backend_and_handle_response`
  passes `response.retry_after_s` into `self.done(...)` on the `not response.ok` path; `done`
  threads it. `src/docket/core/runtime_driver.py::TurnResult`: keyword-only field
  `retry_after_s: float | None = None` **after** `failure_kind`, so positional construction is
  unchanged (`tests/integration/test_retries_and_timeouts.py::test_positional_construction_still_works_without_failure_kind`
  is the oracle). `src/docket/edges/adapters/docket_runtime.py::run_turn`: the final
  `TurnResult(...)` gains `retry_after_s=result.retry_after_s`. `src/docket/core/dispatch.py`
  hop retry loop: the `ctx.do_sleep(...)` line and the `hop_retry` JSON payload (`"retry_after_s"`).
  `src/docket/config.py`: `DISPATCH_RETRY_MAX_WAIT_S = float(os.environ.get(..., "60"))` beside
  `DISPATCH_RETRY_BACKOFF_S`, with the same comment style; `docs/commands.md` env table regenerates
  from it (`gen_cli_docs.py`).
- **Tests you own.** `tests/integration/test_retries_and_timeouts.py::TestHopRetryLoop` (RED: the
  scripted runner returns `TurnResult(..., failure_kind="daemon_error", retry_after_s=7.0)` then
  ok; assert `do_sleep` saw `7.0`; base fails with `TypeError: unexpected keyword`); the ceiling
  case; `tests/integration/test_llm_port.py::TestTransport` one case: fake 429 with
  `Retry-After: 7` -> `retry_after_s == 7.0`; 400 with the header -> `None`.
- **Do not touch:** `_headers`, `resolve_endpoint`, `client_for`, `build_payload`,
  `decode_response`; retry counts; `_RETRYABLE_STATUS`.
- **Goldens:** none.

## P29-7 — `docket auth` is a removed command, and `keys setup` asks for what the catalog needs

Branch `p29-7-retire-auth`. Spec `specs/api/cli-interface.spec.md` -> 1.42.0: delete the
`#### docket auth` section and the `keys`/`auth` note above it; add `auth` to the removed-commands
list with its notice text. `specs/functional/api-keys.spec.md` -> 1.6.0: `setup` **MUST** prompt
for every built-in provider credential the catalog declares, in catalog order, using its
`credentialPrefix` as the format hint.

- **Where.** `src/docket/__main__.py::_REMOVED["auth"] = ("docket auth was removed — store a
  provider key with: docket keys add <NAME>; register an endpoint with: docket models provider
  add",)`. `src/docket/cli/_keys.py`: delete `run_auth` and every helper only it uses
  (`_auth_*`, the `--provider` extraction — check `TestExtractProviderHelper` in
  `test_provider_agnosticism.py`: if the helper is only used by `auth`, delete the helper and that
  test class too, and say so). `_keys_setup`: replace the five-tuple list with
  `[(c, spec.name, getattr(spec, "credential_prefix", "")) for spec in built-in catalog order
  for c in spec.auth.credentials]`. P29-2 ships `credentialPrefix` and merges **after** you
  (merge order P29-5, P29-7, P29-2), so your base does not have the field: read it with
  `getattr` as shown and say so in the return; the integrator drops the `getattr` at the rollup.
  If your base has no built-in documents yet either (P29-2 also ships those), the wizard iterates
  an empty catalog and asks nothing — write the test against a catalog seeded in the isolated
  home, not against the built-ins.
  `src/docket/cli/__init__.py`: delete the `auth` Typer command and its help entry.
- **Tests you own.** `tests/integration/test_provider_agnosticism.py::TestAuthProviderGoneHonestly`
  -> delete; add one case to the existing removed-commands test (locate with `rg -n "_REMOVED"
  tests/`): `docket auth login` exits 1 printing the notice (RED: on the base `auth` is live).
  `keys setup` case: scripted `getpass` input on an isolated home asks for the credentials in
  catalog order.
- **Goldens:** `tests/golden/cases/readonly/help.golden`, `tests/golden/cases/writers/completions_bash.golden`,
  `completions_zsh.golden` lose their `auth` lines — regenerate those three only, list the lines.
  `docs/commands.md` regenerates.
- **Do not touch:** `_validate_key_format`/`_KEY_PREFIXES` (P29-2), anything under
  `docket keys` other than `setup`.

## P29-3 — registration verifies with the credential, and a provider round-trips through the CLI

Branch `p29-3-provider-cli`. Spec `model-profiles.spec.md` -> 2.13.0 ("Provider readiness" 3:
the probe runs with the resolved credential; the classification table from ADR 0011 §4 becomes
requirement text; rule 4/5 wording re-trued). `specs/api/cli-interface.spec.md` -> 1.40.0
(`docket models`: the five `provider` actions with signatures; `preset` no longer requires a
registered block; `--name` removed from the shortcut).

- **Where.** `src/docket/edges/adapters/llm.py`: new `probe_models(endpoint, timeout) ->
  ProbeResult` (dataclass `status: int | None`, `transport_error: str`, `model_ids: list[str]`),
  GET `<base>/models` with `OpenAIChatClient(endpoint)._headers()`; never raises. New function
  only. `src/docket/core/provider.py`: `verify_endpoint(spec, probe) -> ProviderVerification`
  (pure; `probe` is injected so tests pass a fake `ProbeResult`), `register_provider(spec, *,
  probe=None) -> Registration` (default probe builds the `Endpoint` via `resolve_endpoint(f"{name}/x")`
  and calls `probe_models`; refuses when `reachable` is `False`; `save_provider`; `audit_log("provider.add", ...)`
  with name, scope, status, never a value), `remove_provider(name)` (refuses a built-in with no
  global override: `ProviderError` naming `built-in`), `export_provider(name) -> str` (YAML via
  `yaml.safe_dump` of `model_dump(by_alias=True, exclude_defaults=True)` with `kind: provider`
  first; round-trip proven). Delete `ping_endpoint`, `local_provider_config`,
  `register_local_provider`, `ProviderRegistration`, `DEFAULT_MODEL_NAME`, `DEFAULT_PROVIDER`,
  `DEFAULT_BASE_URL`, `DEFAULT_MODEL_ID`, `DEFAULT_CTX`, `DEFAULT_MAX_TOKENS` (the shortcut's
  defaults for a bare `add` come from the built-in `local` document; `docs/QUICK-START-DOCKET.md`
  and `scripts/maint/capture-doc-journey.sh` pass explicit values already — verify).
  `src/docket/cli/_provider.py`: `run_provider(action, args)` dispatching `add` (file or shortcut,
  `--credential NAME`, no `--name`), `list`, `show [--json]`, `remove`, `export [<file>]`; warnings
  printed verbatim from `verification.warning`; keep `_print_local_selection` and re-check its
  strings against `TestProviderGuidanceStringsAreReal`. `src/docket/cli/__init__.py`: the
  `models provider` branch dispatches every action; `_cmd_models_preset` deletes the
  `if preset in ("anthropic", "openai", "google", "local")` refusal block and, after applying,
  prints one readiness line from `model_readiness(std)` (credential present / missing by name).
- **Tests you own.** `tests/integration/test_provider_registration.py` (rewrite the module
  docstring; RED: a local `http.server` answering 401 on `/models` -> exit 0, document stored,
  output names the credential; negative: no listener -> exit 1, nothing stored, i.e.
  `test_ping_failure_is_fail_closed_and_does_not_persist` kept as is); the 200-with-suggestions
  case; the `export` -> fresh home -> `add` -> identical `show --json` round trip; `preset
  anthropic` on a fresh home exits 0 and names `ANTHROPIC_API_KEY`. `tests/integration/test_provider_agnosticism.py::TestLocalPresetCli`
  and `::TestProviderGuidanceStringsAreReal` unedited and green. `tests/agent/release/test_starter_journey.py`
  runs the shortcut — unedited.
- **Goldens:** `help.golden`, `completions_*.golden` (new `provider` actions), `docs/commands.md`
  — list the lines.
- **Do not touch:** `_headers`, `Endpoint`, `AuthSpec` (P29-4); `cli/_config.py`, `cli/_doctor.py`
  (P29-6).

## P29-4 — a provider can authenticate by header and send static headers

Branch `p29-4-auth-header`. Spec `model-profiles.spec.md` -> 2.14.0 (section "Provider catalog":
`auth.type: header` requires `auth.header`; `headers` are sent verbatim after the credential
header; `Authorization`, `Content-Type`, `Accept` are reserved and refused at load).

- **Where.** `src/docket/core/provider.py::AuthSpec`: `type: Literal["bearer", "header", "none"]`,
  `header: str = ""` (required non-empty iff `type == "header"`); `ProviderSpec.headers:
  dict[str, str] = {}` with a validator refusing the three reserved names case-insensitively
  (`ProviderError` field `headers`). `src/docket/core/llm.py::Endpoint`: add `auth_type:
  Literal["bearer", "header", "none"] = "bearer"`, `auth_header: str = ""`, `headers:
  Mapping[str, str] = field(default_factory=dict)` — frozen dataclass, so use `types.MappingProxyType`
  or a tuple of pairs; remove `is_local` and its one assertion in `test_llm_port.py`.
  `src/docket/edges/adapters/llm.py::_headers`: per ADR §3; the `Endpoint(...)` construction
  inside `resolve_endpoint` fills the three fields from the document (the only lines of
  `resolve_endpoint` you own).
- **Tests you own.** `tests/integration/test_llm_port.py::TestTransport` (RED: `auth: {type:
  header, header: api-key}` document + env key -> the fake server sees `api-key: k` and no
  `Authorization`; base fails at `AuthSpec` validation); `tests/unit/core/test_provider.py`:
  `headers: {Authorization: x}` -> `ProviderError` naming `headers` — this is the card's one
  permitted negative case (a reserved header is refused at load, fail closed).
  `test_no_auth_header_without_a_key`, `test_bearer_header_when_a_key_is_present` unedited.
- **Do not touch:** `complete` (P29-5 merged before you), `probe_models` (P29-3 in parallel —
  it calls `_headers`, so keep the signature `self._headers() -> dict[str, str]`).
- **Goldens:** none.

## P29-6 — `config explain` names the provider and its scope, and every doc says the same thing

Branch `p29-6-provider-explain`. Runs after P29-3 and P29-4 merge. Spec `model-profiles.spec.md`
-> 2.15.0 (observability: `config explain` MUST report provider name, scope, dialect, base URL,
credential source and exact-row limits; `doctor` MUST report a malformed global document);
`specs/api/cli-interface.spec.md` -> 1.41.0 (`config explain` JSON keys; `doctor` line).

- **Where.** `src/docket/cli/_config.py::_explain`: new `report["provider"]` built from
  `resolve_endpoint(model)`, `load_catalog().source_of(prefix)`, `resolve_credential(spec)`;
  `_render_human` prints it under the model line. `src/docket/cli/_doctor.py`: new
  `_check_provider_catalog() -> int` (loads every global document through the loader, prints
  `file field: message` per failure) called from the main pass and the `--json` builder next to
  the overlay-problems check. Docs: `docs/CONFIGURATION.md` (§3.1 table rows: "Register an
  endpoint" now `provider add <file.yaml>` or the shortcut; new rows for `list/show/remove/export`;
  the file table: `docket-providers.json` row, `fleet.json` row loses `providers{…}`, add
  `templates/providers/` under built-in; delete the "provider display name derives from `--model`"
  bullet; the key lookup order sentence), `docs/MODEL-GATEWAYS.md` (rewrite "Other
  OpenAI-compatible endpoints" around the document and `export`; in "Compatibility does not mean
  feature parity" replace "does not yet honor `Retry-After`" with the ceiling rule; add the
  Anthropic/Google evaluation-only/beta sentence), `docs/troubleshooting.md` §1 (an error the
  P29-3 path produces, e.g. the 401 warning at `provider add`, and `docket models provider show`
  as the diagnosis) and the later sentence "OpenRouter … and Vercel AI Gateway … have built-in
  mappings" (locate with `rg -n "built-in mappings" docs/`; now every built-in document has one),
  `docs/QUICK-START-DOCKET.md` (one sentence on `export`). Return the README
  "Compatible HTTP" bullet rewrite as a line.
- **Tests you own.** The file with `SUBJECT = "docket.cli._config"` (locate with `rg -n
  'SUBJECT = "docket.cli._config"' tests/`): RED `report["provider"]["scope"] == "global"` for an
  agent on a global document (base: `KeyError`). `cli/_doctor.py` test file: a global document
  with `auth: {type: oauth}` is named with its field.
- **Goldens:** `config explain` cases if any exist under `tests/golden/cases/` — list lines;
  `docs/commands.md` regenerates.
- **Do not touch:** any `core/` or `edges/` file.
