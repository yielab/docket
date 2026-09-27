# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> ## ▶ ACTIVE BOARD — WAVE 48 (opened 2026-09-27): Phase 29, the provider catalog (D-45)
>
> Wave 47 (P29-1, the document model and the `fleet.json` -> `docket-providers.json`
> migration) merged 2026-09-27 at `0be9812`, rollup after it. Wave 48 runs P29-2, P29-5 and
> P29-7 in parallel (merge order P29-5, P29-7, P29-2), one Sonnet worker per card in an
> isolated worktree under one integrator; packets in
> [.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
> Wave 49 (P29-3, P29-4, then P29-6) opens only after the Wave 48 rollup merges green.
>
> **☑ Phase 28 complete (2026-09-26).**
>
> **Phase 28 closed 2026-09-26** (ROADMAP D-44, [ADR 0010](docs/adr/0010-config-format-v1-and-extension-points.md)):
> eight cards over Waves 44–46, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> What shipped: the `kind` envelope and `docket validate`, short forms for policies, pipelines
> and roles over the unchanged canonical form, structured policy predicates, `on:` outcome
> routing with bounded loops, `when` skips and command steps, operator-scoped hashed predicate
> plugins, generated schemas and short-form export.
>
> Waves 44 and 45 (P28-1..P28-6) merged 2026-09-26 (rollups `ea9e354`, Wave 45 rollup after
> `5622d13`). Wave 46 runs P28-7 (predicate plugins) and P28-8 (schemas, short-form export, docs)
> in parallel; packets (Wave 46 section) in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> Phase 28 closes when the Wave 46 rollup merges green.
>
> **☑ Phase 27 complete (2026-09-26).**
>
> **Phase 27 closed 2026-09-26** (ROADMAP D-43, [ADR 0009](docs/adr/0009-per-pod-configuration-and-portable-teams.md)):
> ten cards over Waves 41–43, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-41-worker-packets.md](.agents/handoffs/wave-41-worker-packets.md).
> What shipped: pod role overlays and pod policies (`--pod`), MCP servers that declare `kind`
> and `tools`, pod `mcpServers`/`deniedTools` with live readers, the Lead's instruction as
> archetype data, `docket pod <p> apply|export` with a round-trip proof, scope labels in
> `config explain`/`doctor`. Two defects found and fixed inside the phase: pod-overlay roles were
> dropped from the roster (P27-9) and `apply` skipped policies (P27-10).
>
> **◇ WAVE 37 CLOSED (2026-09-25) — no card claimed.**
>
> **Wave 37 closed 2026-09-25** (ROADMAP D-41). A bounded triage ran the product on six surfaces
> and found twelve reproducible defects; six cards fixed them in two batches of one-card Sonnet
> workers under one integrator, archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets stay in
> [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md). Live
> evidence on the local endpoint: the journey's dispatch scene reaches `done — 3 hop(s)` with the
> reviewer's `APPROVE`, and a `cd`-prefixed production push still asks.
>
> **◇ PHASE 26 CLOSED (2026-09-26) — the configuration contract (D-42).**
>
> **Phase 26 closed 2026-09-26**, 20/20 cards over Waves 38–40, one integrator + one Sonnet
> worker per card in isolated worktrees; the full board section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-38-worker-packets.md](.agents/handoffs/wave-38-worker-packets.md).
> What shipped: fail-closed policies, visible prompt truncation with window-scaled budgets,
> `docket pod <p> config` (nine typed keys), bindable pipelines, step instructions with
> `--var`, `docket config explain`, one default model of record, registry retention,
> `INSTRUCTIONS.md` + `pod sync`, `projectInstructions`, loud doctor config errors, and three
> shipped recipes. Reasoning: [ADR 0008](docs/adr/0008-configuration-contract.md); user guide:
> [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
>
> **Follow-ups parked with named triggers** (small, none scheduled): serve.py's webhook does not
> catch a bound-pipeline `DispatchError`; `cli/_agents.py`/`cli/_install.py` carry their own copy
> of the retired HEARTBEAT-write instruction; `doctor --json` lacks the new checks; pod
> subcommand completions omit `set-verify`/`sync`; `cli-interface.spec.md` prose for
> `runs prune`/`conversations prune`.
>
> `v0.2.0-beta.3` (2026-09-18) is the latest release; the next beta stays a maintainer action.
> A card becomes claimable only when the integrator opens a planned section below and confirms its
> batching from function-level contention.
>
> **Measured, not scheduled:** `tee` is on the bash allowlist, so `echo x | tee f` writes a file
> without asking (pre-existing, not introduced by W37-C1); `docket help <command>` renders through
> `typer.testing.CliRunner`; `turnTimeoutS`/`verifyTimeoutS` gained their typed writer in
> Phase 26 (P26-4), superseding the earlier "no dedicated writer" note here. A new wave starts from bounded triage, not from this note.
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump + changelog entry (integrator-applied in a
   multi-agent wave), **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** **`main`** is the canonical public/default and release lineage (D-31). Use one
short-lived card branch or isolated worktree per task and integrate it into `main` without rewriting
history. `platform` may remain as a synchronized historical/integration ref, but it is not a second
release source.

---


## ▶ WAVE 48 — ACTIVE (opened 2026-09-27): Phase 29, the provider catalog (D-45)

**Opened 2026-09-27 (Wave 48 active; Wave 47 done; Wave 49 queued in this section).** Seven cards in three waves. Decision, the document, the two scopes, the
adapter seam, the twelve amended spec rules, the retired-code table and the verdict table are in
[docs/adr/0011-provider-catalog.md](docs/adr/0011-provider-catalog.md). Worker packets:
[.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 28 closed at `56e8d9d`; batching confirmed from the
function-level ownership below; the packets file records the base commit and the spec versions
Phase 28 consumed (`pod-dispatch` → 6.21.0 for P29-5, `config-format` → 1.2.0 for P29-1, which
now also adds the `provider` arm to `load_document`).

**Trigger (explicit request + deterministic regression, 2026-09-26):** provider selection must be
configurable like roles, policies and pipelines, with abstractions that make agnosticism real, no
overengineering and no legacy left behind. Reproduced on `0764091`: `docket models preset
anthropic` demands a registered block; `docket models provider add anthropic
https://api.anthropic.com/v1 --model claude-sonnet-4-6` refuses because the unauthenticated probe
of `/models` gets 401 (openai 401, google 404) and `HTTPError` is read as unreachable; no bypass
exists. Evidence locators are in the ADR's evidence table.

**Test rule (ADR 0011):** one RED behavioural test per card in the module's `SUBJECT` file; a
negative case only for a fail-closed property (P29-1, P29-3); existing tests, goldens and specs
are the no-change oracle; no agent-lane tests, no guards; goldens change only where a card lists
the lines.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 47 | P29-1 | `core/provider.py` (rewritten), `config.py::PROVIDERS_FILE`, `core/fleet.py` (delete `add_local_provider`/`get_local_provider`; comment on the field), `edges/adapters/llm.py::resolve_endpoint` + `::client_for` only, one-line swaps in `cli/__init__.py::_cmd_models_preset` and `cli/_agents.py`, test seeding sites |
| 48 | P29-2 ∥ P29-5 ∥ P29-7 | `core/provider.py`: P29-2 owns new derivation functions + its fields; `core/models_policy.py`, `templates/providers/`, `cli/_doctor.py` (the `_PROVIDER_KEY` users), `cli/_keys.py::_validate_key_format`, `scripts/gen_cli_docs.py` → P29-2; `core/llm.py::ChatResponse`, `edges/adapters/llm.py::complete` (`HTTPError` branch), `core/agent_loop.py` (`call_backend_and_handle_response`, `done`), `core/runtime_driver.py::TurnResult`, `edges/adapters/docket_runtime.py::run_turn` (the `TurnResult(...)` construction), `core/dispatch.py` (the `do_sleep` line), `config.py` → P29-5; `cli/_keys.py::_keys_setup` + `run_auth`, `cli/__init__.py` (the `auth` command), `__main__.py::_REMOVED` → P29-7 |
| 49 | P29-3 ∥ P29-4, then P29-6 | `core/provider.py`: P29-3 owns `verify_endpoint`/`register_provider`/`remove_provider`/`export_provider`, P29-4 owns `AuthSpec` + `headers`; `edges/adapters/llm.py`: P29-3 owns new `probe_models`, P29-4 owns `_headers` + `core/llm.py::Endpoint`; `cli/_provider.py`, `cli/__init__.py` (`models provider` dispatch, `_cmd_models_preset`) → P29-3; `cli/_config.py`, `cli/_doctor.py` (own check), `docs/` → P29-6 after both merge |

Every card follows the §"How to use this board" definition of done.

### P29-1 — a provider is a document, and today's configuration resolves exactly as before

**Status:** DONE (2026-09-27, `0be9812`) · **Size:** M · **Wave:** 47 · **Spec:** `model-profiles.spec.md` → 2.11.0 (new section "Provider catalog"; "Hosted gateway resolution" rule 3 amended; "Provider registration display fields" removed), `config-format.spec.md` → 1.2.0 (`kind: provider` joins the envelope; P28-1 shipped)

**Trigger:**
- `fleet.json → providers` is a loose dict (`core/fleet.py::FleetConfig.providers`, "kept as a
  loose dict"); one model per block; `api`/`name`/`cost`/`reasoning`/`input` are written and read
  by nothing (spec "Provider registration display fields").
- `core/llm.py`'s docstring reserves room for a second dialect; nothing selects the adapter today
  (`edges/adapters/llm.py::client_for` constructs `OpenAIChatClient` unconditionally).

**Goal:**
- `core/provider.py::ProviderSpec` (pydantic, `populate_by_name`, camelCase aliases) with exactly
  the fields this card consumes: `name` (`^[a-z0-9][a-z0-9-]*$`), `dialect: Literal["openai-chat"]`,
  `baseUrl` (http/https), `auth: AuthSpec{type: Literal["bearer","none"], credentials: list[str]}`
  (each `^[A-Z][A-Z0-9_]*$`; `bearer` requires ≥ 1; `none` requires 0), `local: bool`,
  `models: list[ModelRow{id, contextWindow: int|None > 0, maxTokens: int|None > 0}]` (unique ids),
  `note: str`. `local: true` defaults `auth.type` to `none`.
- `load_provider_document(path) -> ProviderSpec`: YAML (JSON included), requires `kind: provider`
  and `name`; raises `ProviderError(file, field, message, valid)` — an unknown `dialect` or
  `auth.type` names the valid values.
- `Catalog` = built-in (`templates/providers/*.yaml`, empty until P29-2) + global
  (`config.PROVIDERS_FILE` = `DOCKET_HOME/docket-providers.json`, shape `{"providers": {name:
  spec}}`), nearest-wins by name; `load_catalog() -> Catalog`, `Catalog.get(name)`,
  `Catalog.source_of(name) -> "built-in" | "global"`, `save_provider(spec)` and
  `delete_provider(name)` through `edges/store.py`.
- `resolve_credential(spec) -> tuple[str, str]` (value, source ∈ `override|env|store|none`):
  `DOCKET_LLM_API_KEY` → env → store, per name in `auth.credentials`, first present wins.
- `migrate_fleet_providers()` on first `load_catalog()`: ports each `fleet.json → providers`
  block (`apiKey` `"local"`/empty → `auth: none`; loopback URL or all-zero `cost` → `local: true`;
  a literal non-placeholder `apiKey` → stored under `<NAME>_API_KEY` via `core/secrets.py` and
  referenced by name, audited `provider.migrate`; display fields dropped), writes the destination,
  then clears the fleet field. Idempotent. `FleetConfig.providers` stays for this read only (comment
  says so; removal deferred one release).
- `edges/adapters/llm.py::resolve_endpoint` reads the catalog instead of `get_local_provider`; for
  a provider absent from the catalog it keeps today's `_HOSTED_GATEWAY_BASE_URLS` / derived
  `<PREFIX>_API_KEY` path untouched (P29-2 retires it). `client_for` dispatches on
  `spec.dialect` over `_DIALECTS = {"openai-chat": OpenAIChatClient}` and returns `None` for
  anything else.
- Delete `core/fleet.py::add_local_provider` and `::get_local_provider`; swap every caller and
  every test seed (`tests/integration/test_llm_port.py` monkeypatches, `test_install.py`,
  `test_maintain_rebuild.py`, `test_provider_registration.py` reads) to the catalog. One-line swaps
  in `cli/__init__.py::_cmd_models_preset` (`registered = load_catalog().get(preset)`) and
  `cli/_agents.py` (the `fleet.providers` foundation check → global catalog non-empty).
  `register_local_provider` keeps its signature and writes through `save_provider` (P29-3 rewrites it).

**Non-goals:** built-in documents, presets, prices, key prefixes (P29-2); `auth: header`, `headers`
(P29-4); verification changes and the CLI actions (P29-3); any doc outside the spec.

**Owns:** `core/provider.py` (whole file), `config.py::PROVIDERS_FILE`, `core/fleet.py` (the two
functions, the field comment), `edges/adapters/llm.py::resolve_endpoint` and `::client_for` only,
the one-line call-site swaps named above, the test seeding sites named above.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `fleet.json` with this machine's `local` block (URL `http://127.0.0.1:8081/v1`, ctx 16384, max 8192, `apiKey: local`) in a fresh `DOCKET_HOME` | `resolve_endpoint("local/<id>")` returns the same `Endpoint` (base URL, empty key, 16384, 8192) as on the base; `docket-providers.json` holds `{"providers": {"local": {... "auth": {"type": "none"}, "local": true, ...}}}`; `fleet.json` has no `providers` content; a second load writes nothing |
| a fleet block with a literal `apiKey: sk-test-123` | the value is in the central store under `<NAME>_API_KEY`, the document references the name, one `provider.migrate` audit entry, the value never appears in `docket-providers.json` |
| document with `dialect: grpc` | `ProviderError` naming `dialect` and `openai-chat` (negative case) |
| document with `auth: {type: bearer, credentials: []}` | `ProviderError` naming `auth.credentials` |
| `resolve_endpoint("openrouter/openrouter/free")` with no document | unchanged (`https://openrouter.ai/api/v1`) — `TestEndpointResolution` untouched and green |

**RED:** `tests/unit/core/test_provider.py`: `from docket.core.provider import load_provider_document`
fails on the base; `tests/integration/test_llm_port.py`: the migration case above fails on the base
because `docket-providers.json` is never written.

### P29-2 — the providers docket knows are documents, and every table derives from them

**Status:** IN-PROGRESS (@sonnet-p29-2) · **Size:** M · **Wave:** 48 · **Spec:** `model-profiles.spec.md` → 2.12.0 ("Presets" 1, "Hosted gateway resolution" 2, "Provider readiness" 2, "Pricing" 1/3/4 amended), `api-keys.spec.md` → 1.5.0 ("Propagation" 3 amended)

**Trigger:** seven tables, seven populations (ADR 0011 evidence row 1); `docket doctor` asks for
`GROQ_API_KEY` for a model `resolve_endpoint` cannot resolve; `resolve_endpoint("anthropic/…")` is
`None` on a fresh install although the preset is the default.

**Goal:**
- `ProviderSpec` gains, each with its reader in this card: `presets: list[Preset{name, ranks{economy,
  standard, premium}, note}]`, `marketplace: bool`, `credentialPrefix: str`, `pricesAsOf: str`
  (`YYYY-MM-DD`, required when any row has a price), `ModelRow.price: Price{input, output,
  cacheRead, cacheWrite}` (USD per MTok, ≥ 0).
- `src/docket/templates/providers/*.yaml`: `anthropic`, `openai`, `google`, `openrouter` (presets
  `openrouter` and `openrouter-free`, `marketplace: true`), `ai-gateway` (`credentials:
  [AI_GATEWAY_API_KEY, VERCEL_OIDC_TOKEN]`, `marketplace: true`), `groq`, `mistral`, `deepseek`,
  `xai`, `cerebras`, `together`, `ollama` (`http://127.0.0.1:11434/v1`, `local: true`), `lmstudio`
  (`http://127.0.0.1:1234/v1`, `local: true`), `local` (today's `DEFAULT_BASE_URL`, `local: true`,
  no rows). Ranks, prices and `pricesAsOf` copied from today's `PRESET_TABLE`/`MODEL_PRICING`
  verbatim; the `anthropic`/`google` preset notes carry the vendor's own evaluation-only / beta
  wording (ADR 0011 evidence, last row). Built-in files are validated by the same loader in a test.
- `core/models_policy.py`: `presets()`, `preset_table()`, `is_local_provider(prefix)`,
  `is_marketplace(prefix)`, `price_for(model)`, `rank_anchors()` (= built-in `anthropic` preset
  ranks) replace `KNOWN_PRESETS`, `PRESET_TABLE`, `LOCAL_PROVIDERS`, `UNPRICED_MARKETPLACE_PROVIDERS`,
  `MODEL_PRICING`, `MODEL_PRICING_AS_OF` and the `_RANK_ANCHORS` literal; `pricing_label`,
  `validate_model`, `load_registry`, `find_registry_problems`, `write_registry` and
  `core/utils.py::estimate_cost_usd` read them. `MODEL_ALIASES` stays.
- `edges/adapters/llm.py`: delete `_HOSTED_GATEWAY_BASE_URLS` and the `PROVIDER_CREDENTIAL_NAMES`
  import; a provider absent from the catalog resolves only under `DOCKET_LLM_BASE_URL` (with the
  derived `<PREFIX>_API_KEY` env name), else `None`. `core/provider.py`: delete
  `PROVIDER_CREDENTIAL_NAMES`; `model_readiness` reads the catalog.
- `cli/_doctor.py`: `_check_provider_coverage` and the JSON twin read `auth.credentials` from the
  catalog (delete `_PROVIDER_KEY`). `cli/_keys.py::_validate_key_format` reads `credentialPrefix`
  (delete `_KEY_PREFIXES`). `scripts/gen_cli_docs.py::_provider_credential_names` reads the catalog.
- `config.DEFAULT_MODEL` stays the one literal; a test pins it to the built-in `anthropic` preset's
  `standard` rank.

**Non-goals:** the `preset` command's registration check and the `provider` CLI (P29-3); docs
(P29-6); `keys setup` (P29-7).

**Owns:** `core/provider.py` (the fields above and new derivation helpers only), `core/models_policy.py`,
`core/utils.py::estimate_cost_usd`, `templates/providers/`, `edges/adapters/llm.py` (the two
deletions only), `cli/_doctor.py` (the two `_PROVIDER_KEY` readers), `cli/_keys.py::_validate_key_format`,
`scripts/gen_cli_docs.py::_provider_credential_names`, `tests/unit/core/test_provider.py`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fresh `DOCKET_HOME`, `resolve_endpoint("anthropic/claude-sonnet-4-6")` | `https://api.anthropic.com/v1`, empty key, 200000 / 64000 from the row |
| global document `anthropic` with another `baseUrl` | the global wins; `Catalog.source_of("anthropic") == "global"` |
| `docket models preset` (list) | the seven names of today plus every built-in preset; `openrouter-free` note unchanged |
| `pricing_label("local/x")`, `("openrouter/anything")`, `("groq/x")` | `$0 (local)`, `n/a (bring your own)`, `n/a` — `TestPricingHonesty` untouched and green |
| every file in `templates/providers/` | loads through `load_provider_document` |
| AST test | no dict/tuple literal containing `"anthropic"` or `"openai"` outside `core/provider.py` and `templates/` |

**RED:** `tests/unit/core/test_provider.py`: replace `test_five_known_providers` with the AST test
above (fails on the base on `_PROVIDER_KEY`) and a test that `load_catalog().get("anthropic")` is
non-`None` on a fresh home (fails on the base).

### P29-3 — registration verifies with the credential, and a provider round-trips through the CLI

**Status:** TODO · **Size:** M · **Wave:** 49 (after P29-2) · **Spec:** `model-profiles.spec.md` → 2.13.0 ("Provider readiness" 3/4 amended; classification table added), `cli-interface.spec.md` → 1.40.0 (`docket models provider` actions; `preset` no longer requires a block)

**Trigger:** the reproduction in this section's header. `ping_endpoint` also performs network I/O
inside `core/` (side effects belong in `edges/`).

**Goal:**
- `edges/adapters/llm.py::probe_models(endpoint, timeout) -> ProbeResult{status: int|None,
  transport_error: str, model_ids: list[str]}` — GET `<baseUrl>/models` with the same headers
  `complete` would send; never raises.
- `core/provider.py::verify_endpoint(spec) -> ProviderVerification{reachable, status,
  credential_present, credential_name, advertised: list[str], warning: str}` — pure classification of
  a `ProbeResult` per the ADR §4 table; `register_provider(spec) -> Registration{spec, verification,
  changed}` refuses only when `reachable` is `False`, writes global scope, audits `provider.add`;
  `remove_provider(name)` (global only; a built-in name with no override refuses naming the scope),
  audits `provider.remove`; `export_provider(name) -> str` writes the ADR §1 document omitting
  defaults. Delete `ping_endpoint`, `local_provider_config`, `register_local_provider`,
  `ProviderRegistration`, `DEFAULT_MODEL_NAME`, `DEFAULT_PROVIDER/BASE_URL/MODEL_ID/CTX/MAX_TOKENS`
  (the shortcut's defaults come from the built-in `local` document).
- `cli/_provider.py`: `add <file.yaml>` and the existing `add <name> <base-url> --model <id>
  [--ctx] [--max-tokens] [--credential NAME]` shortcut (builds the same `ProviderSpec`; `--name`
  is dropped: the display label no longer exists), `list`, `show <name> [--json]`, `remove
  <name>`, `export <name> [<file>]`; warnings printed literally from `verification.warning`;
  `_print_local_selection` strings re-checked against `TestProviderGuidanceStringsAreReal`.
- `cli/__init__.py`: `models provider <action>` dispatch; `_cmd_models_preset` drops the
  "registered block" refusal and instead prints the readiness line (credential name present or
  missing) after applying, for every preset alike.

**Non-goals:** `auth: header`/`headers` (P29-4); explain/doctor/docs (P29-6).

**Owns:** `core/provider.py` (the functions named), `edges/adapters/llm.py::probe_models` (new
function only), `cli/_provider.py`, `cli/__init__.py` (`models provider` dispatch and
`_cmd_models_preset` only), `tests/integration/test_provider_registration.py`. Adds CLI surface:
`help` and completions goldens, `docs/commands.md`, listed line by line.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fake HTTP server answering 401 on `/models`; `docket models provider add hosted http://127.0.0.1:<p>/v1 --model m --credential HOSTED_API_KEY` | exit 0, the document is stored, output names `HOSTED_API_KEY`, `verification.status == 401` |
| no server listening | exit 1, nothing stored — `test_ping_failure_is_fail_closed_and_does_not_persist` unchanged and green (negative case) |
| server answering 200 with `{"data":[{"id":"a"},{"id":"b"}]}` and a document listing only `a` | stored; `b` printed as a suggestion; `models[]` still has one row |
| `export local > f.yaml` on this machine's document; fresh home; `add f.yaml` | `show local --json` identical on both homes |
| `docket models preset anthropic` on a fresh home with no key | exit 0, policy applied, one line naming `ANTHROPIC_API_KEY` as missing; `docket init` still stops at step 5 |
| `remove anthropic` with no global override | exit 1 naming the built-in scope |

**RED:** `tests/integration/test_provider_registration.py`: the 401 case fails on the base with
"Provider was not registered".

### P29-4 — a provider can authenticate by header and send static headers

**Status:** TODO · **Size:** S · **Wave:** 49 · **Spec:** `model-profiles.spec.md` → 2.14.0 ("Provider catalog": `auth.type: header`, `auth.header`, `headers`, the reserved-header rule)

**Trigger:** the adapter sends `Authorization: Bearer` or nothing (`OpenAIChatClient._headers`);
Azure OpenAI authenticates with an `api-key` header and multi-workspace Anthropic keys need
`anthropic-workspace-id`; `Endpoint.is_local` has no consumer outside one test.

**Goal:**
- `AuthSpec.type` gains `"header"` with a required `header: str`; `ProviderSpec.headers:
  dict[str, str]` whose keys may not be `authorization`, `content-type` or `accept`
  (case-insensitive; `ProviderError` otherwise).
- `core/llm.py::Endpoint` gains `auth_type`, `auth_header`, `headers` (frozen, defaults keep
  today's behaviour) and loses `is_local`; `resolve_endpoint` fills them from the document.
- `OpenAIChatClient._headers()`: `bearer` → `Authorization: Bearer <v>`; `header` → `<auth.header>:
  <v>`; `none` → no credential header; then `headers`. `probe_models` (P29-3) reuses `_headers`.

**Non-goals:** query-parameter auth (deferred); any second dialect.

**Owns:** `core/provider.py::AuthSpec` and the `headers` field only, `core/llm.py::Endpoint`,
`edges/adapters/llm.py::_headers` and the `Endpoint(...)` construction inside `resolve_endpoint`,
the one `is_local` test.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| document `auth: {type: header, header: api-key, credentials: [AZURE_KEY]}`, `headers: {x-title: docket}`; env `AZURE_KEY=k` | the POST carries `api-key: k` and `x-title: docket` and no `Authorization` |
| document `headers: {Authorization: x}` | `ProviderError` naming `headers` |
| a bearer document | request headers byte-identical to today — `TestTransport` untouched and green |

**RED:** `tests/integration/test_llm_port.py::TestTransport`: the header case fails on the base
(`AuthSpec` rejects `header`).

### P29-5 — a retry waits as long as the provider asked, up to a ceiling

**Status:** IN-PROGRESS (@sonnet-p29-5) · **Size:** M · **Wave:** 48 · **Spec:** `pod-dispatch.spec.md` → 6.21.0 (6.18–6.20 were consumed by Phases 27–28) ("Retries and the failure-kind taxonomy")

**Trigger:** `core/dispatch.py` sleeps `DISPATCH_RETRY_BACKOFF_S * attempt` (2 s, 4 s) and
`edges/adapters/llm.py::complete` discards response headers; a 429 with a 60 s window exhausts
`DISPATCH_RETRIES_DEFAULT` in 6 s. `docs/MODEL-GATEWAYS.md` states the gap.

**Goal:**
- `core/llm.py::ChatResponse.retry_after_s: float | None`; `complete`'s `HTTPError` branch parses
  `Retry-After` (integer seconds, or an HTTP-date as a non-negative delta) when the status is
  retryable; anything unparseable → `None`.
- `core/agent_loop.py`: `call_backend_and_handle_response` passes it to `done(...)`;
  `AgentLoopResult.retry_after_s`; `core/runtime_driver.py::TurnResult.retry_after_s: float |
  None = None` (keyword-only, positional construction unchanged — `test_positional_construction_still_works_without_failure_kind` stays green); `DocketDriver.run_turn` forwards it.
- `core/dispatch.py` hop retry loop: `ctx.do_sleep(min(max(_cfg.DISPATCH_RETRY_BACKOFF_S * attempt,
  run_res.retry_after_s or 0.0), _cfg.DISPATCH_RETRY_MAX_WAIT_S))`; the `hop_retry` trace event
  records `retry_after_s`. `config.py::DISPATCH_RETRY_MAX_WAIT_S` (env, default 60).

**Non-goals:** retry counts, jitter, circuit breaking, the `FailureKind` vocabulary.

**Owns:** `core/llm.py::ChatResponse`, `edges/adapters/llm.py::complete` (`HTTPError` branch only),
`core/agent_loop.py` (`call_backend_and_handle_response`, `done`, `AgentLoopResult`),
`core/runtime_driver.py::TurnResult`, `edges/adapters/docket_runtime.py::run_turn` (the
`TurnResult(...)` construction only), `core/dispatch.py` (the `do_sleep` line and the `hop_retry`
payload only), `config.py` (the new constant).

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| scripted runner: attempt 1 → `daemon_error` with `retry_after_s=7`, attempt 2 → ok | `do_sleep(7.0)` once, task done |
| `retry_after_s=3600` | `do_sleep(60.0)` |
| `retry_after_s=None` | `do_sleep(2.0)`, `do_sleep(4.0)` — `test_linear_backoff_sleeps_increase_per_attempt` untouched |
| fake endpoint: 429 with `Retry-After: 7` | `ChatResponse.retry_after_s == 7.0`, `failure_kind == "daemon_error"` |
| 400 with `Retry-After: 7` | `retry_after_s is None` |

**RED:** `tests/integration/test_retries_and_timeouts.py`: the first case fails on the base
(`TurnResult` has no `retry_after_s`).

### P29-6 — `config explain` names the provider and its scope, and every doc says the same thing

**Status:** TODO · **Size:** S · **Wave:** 49 (after P29-3 and P29-4) · **Spec:** `model-profiles.spec.md` → 2.15.0 (observability rules), `cli-interface.spec.md` → 1.41.0 (`config explain` provider section; doctor)

**Trigger:** `docket config explain` reports the model id and nothing about where it goes;
`docs/troubleshooting.md` §1 shows an error a CLI user cannot reach; `docs/CONFIGURATION.md`
maps `providers` to `fleet.json`; `docs/MODEL-GATEWAYS.md` documents one-model blocks.

**Goal:**
- `cli/_config.py::_explain` adds `provider: {name, scope, dialect, baseUrl, credential: {name,
  source}, model: {id, contextWindow, maxTokens, source: "row" | "none"}}` (via `resolve_endpoint`,
  `Catalog.source_of`, `resolve_credential`), rendered in `_render_human`.
- `cli/_doctor.py`: `_check_provider_catalog()` reports each malformed global document (file, field,
  reason) the way `find_overlay_problems` is reported; included in `--json`.
- Docs: `docs/CONFIGURATION.md` (§3.1 command table, the file table rows for
  `docket-providers.json` and `templates/providers/`, the note on display fields removed),
  `docs/MODEL-GATEWAYS.md` (rewritten around the document; the "Compatibility does not mean
  feature parity" list kept and re-trued for `Retry-After`), `docs/troubleshooting.md` §1 (the
  reachable error) and its "built-in mappings" sentence about OpenRouter/AI Gateway (now every
  built-in document), `docs/QUICK-START-DOCKET.md` (unchanged commands; one sentence on `export`).
  README limit bullet "Compatible HTTP, not provider SDK parity" gains the Anthropic
  evaluation-only clause — returned as a line for the integrator (D-37).

**Non-goals:** any code beyond `cli/_config.py` and the one doctor function.

**Owns:** `cli/_config.py::_explain` + `_render_human`, `cli/_doctor.py::_check_provider_catalog`
(new) and its two call sites, the four docs named. `docs/commands.md` regeneration.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| agent on `local/<id>` from this machine's document | `config explain --json` has `provider.scope == "global"`, `credential.source == "none"`, `model.contextWindow == 16384` |
| agent on `anthropic/claude-sonnet-4-6`, `ANTHROPIC_API_KEY` in the store | `scope == "built-in"`, `credential.source == "store"` |
| a global document with `auth.type: oauth` | `docket doctor` names the file and `auth.type`; `--json` carries it |
| `grep -n "api.anthropic.com/v1/..." docs/troubleshooting.md` | shows an error the P29-3 path can produce |

**RED:** `tests/integration/test_config_explain.py` (or the file holding `SUBJECT =
"docket.cli._config"`): `report["provider"]` is absent on the base.

### P29-7 — `docket auth` is a removed command, and `keys setup` asks for what the catalog needs

**Status:** IN-PROGRESS (@sonnet-p29-7) · **Size:** S · **Wave:** 48 · **Spec:** `cli-interface.spec.md` → 1.42.0 (`docket auth` section removed; removed-command list), `api-keys.spec.md` → 1.6.0 (`setup` iterates the catalog)

**Trigger:** every `docket auth` subcommand answers "gone, use `docket keys add`"
(`cli/_keys.py::run_auth`); the project's mechanism for that is `__main__.py::_REMOVED`
(`workflow`, `team`, `eval`); `_keys_setup` holds the seventh provider table.

**Goal:**
- `__main__.py::_REMOVED["auth"]` = one line pointing at `docket keys add <NAME>` and `docket
  models provider`; delete `run_auth` and its helpers, the `auth` Typer command, the
  `--provider` parsing it carried.
- `_keys_setup` iterates the built-in catalog entries that declare `credentials`, in catalog order,
  using `credentialPrefix` as the hint; the five-row tuple is deleted.
- `TestAuthProviderGoneHonestly` is replaced by one case in the existing removed-commands test.

**Non-goals:** anything in `docket keys` beyond `setup` and `_validate_key_format`'s P29-2 change.

**Owns:** `cli/_keys.py::_keys_setup` and `run_auth` (+ helpers), `cli/__init__.py` (the `auth`
command only), `__main__.py::_REMOVED`, `tests/integration/test_provider_agnosticism.py` (the one
class). Goldens: `help`, `completions_bash`, `completions_zsh` lose the `auth` lines — listed.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `docket auth login` | exit 1, the removed-command line, no traceback |
| `docket keys setup` with a fresh home, scripted input | asks for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`, `AI_GATEWAY_API_KEY` and every other built-in credential in catalog order |
| `docket --help` | no `auth` entry |

**RED:** the removed-commands test: `docket auth` prints the `_REMOVED` line on the base — fails
because `auth` is a live command.
