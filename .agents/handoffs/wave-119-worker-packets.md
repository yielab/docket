# Wave 119 worker packet — Phase 45, P45-2 (D-65, ADR 0029 point 2)

Coordinator: the session that ran Waves 117 and 118. **Base commit: the commit that opened Wave
119 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-119-worker-packets.md`),
which carries the Wave 118 rollup (P45-3 protected paths). One card, one worker, one worktree
(`../rack-cli-wt/w119-p45-2`, branch `w119-p45-2`). The card (`python3
.agents/skills/docket-roadmap/scripts/card_packet.py P45-2`) is the contract; this file is the
map. Symbols were located at the base and drift; re-locate every one with `rg -n` before editing.

| Card | Worker | Owning spec bumps |
| --- | --- | --- |
| P45-2 | Sonnet | `model-profiles.spec.md` 3.6.0, `agent-loop.spec.md` 1.42.0, `trace-store.spec.md` 1.13.0 |

## 0. Rules

**Exactly §0 of [wave-117-worker-packets.md](wave-117-worker-packets.md)** (which applies §0 of
wave-98 with its substitutions), with `w119` in place of `w117`, and last-updated 2026-10-20 on
every spec you bump. Never write the word `prill` anywhere.

## The maintainer's decision (2026-10-20): option A

The shipped templates lose their `contextWindow`/`maxTokens` rows **only**. `price`,
`pricesAsOf` and `presets` stay: no provider publishes prices, the labelled estimate and the
budget auto-pause read them, and `rank_anchors()` reads the presets. ADR 0029 point 2 is amended
by the integrator; do not edit `docs/adr/`.

## P45-2 — a model's limits come from the provider's `/models` (Sonnet)

- **First step (evidence, no network).** The "4,096 cut" is the provider's default output cap,
  not a docket request field: `core/agent_loop.py::_resolve_context_bounds` sends `max_tokens`
  only when the endpoint registers an output cap, and uses `config.DEFAULT_MAX_OUTPUT_TOKENS`
  for the window and budget arithmetic only. Cite the recorded run in your return:
  `rg -n '"outputTokens": 4096|finishReason": "length"' internal-docs/joint-run-2026-10-18/replay`
  (gitignored, present on this disk) and the 49 `unknown_window` `request_fit` events named in
  `internal-docs/joint-run-2026-10-18/trace-analysis-2026-10-18.md`.
- **Recorded bodies (the oracle).** Four scrubbed `/models` bodies recorded on 2026-10-20 are at
  `/tmp/claude-1000/-home-ox-Sites-rack-cli/872f3b31-3c3a-4e0a-9383-24809d287d2f/scratchpad/fixtures/`
  (`anthropic.json`, `gateway.json`, `llamacpp.json`, `openrouter.json`). Copy them unchanged to
  `tests/fixtures/provider-models/<name>.json` and commit them. Published limits they carry:
  - Anthropic native (`api.anthropic.com/v1/models`): `max_input_tokens` 1000000 -> window,
    `max_tokens` 128000 -> output cap (`claude-haiku-5-5`, `claude-sonnet-4-6`).
  - llama.cpp (`127.0.0.1:8081/v1/models`): `meta.n_ctx` 32768 -> window, **never**
    `meta.n_ctx_train` (262144); no output cap published -> unknown.
  - Vercel AI Gateway (`ai-gateway.vercel.sh/v1/models`): `context_window`, `max_tokens`
    (`anthropic/claude-sonnet-4.5` 1000000/64000, `anthropic/claude-haiku-4.5` 200000/64000);
    `alibaba/wan-v2.5-t2v-preview` publishes `0`/`0`, which is **unknown**, never a number.
  - OpenRouter (`openrouter.ai/api/v1/models`): `context_length` -> window,
    `top_provider.max_completion_tokens` -> output cap (`openrouter/free` 200000/unknown;
    `minimax/minimax-m3.1-flash:free` 1000000/524288).
  Detect the shape **per row by field presence**, not by provider name; an absent, null,
  non-integer or non-positive value is unknown.
- **Adapter (`edges/adapters/llm.py`).** `ProbeResult` gains the per-id limits (a small frozen
  type: window `int | None`, output cap `int | None`); `probe_models` fills it from the 200 body
  through one field map (`_extract_model_limits`, beside `_extract_model_ids`). RED test first:
  the llama.cpp body parsed to a window of 32768 (fails on the base: `ProbeResult` has no limits).
  `endpoint_from_spec` resolves each limit **declared > observed > unknown**: the declared value
  is the exact `ModelRow` (`contextWindow`/`maxTokens` from `provider add --ctx/--max-tokens` or
  a `kind: provider` document, unchanged), the observed value comes from the store below, and
  unknown is `None`. Keep this module the only one that knows the wire shapes.
- **Store (`core/provider.py`, `config.py`).** `config.PROVIDER_MODELS_FILE = DOCKET_HOME /
  "provider-models.json"`, docket-owned, read and written only through `edges/store.py`. Shape:
  `{"providers": {"<name>": {"observedAt": "<YYYY-MM-DD>", "models": {"<id>": {"contextWindow":
  N|null, "maxTokens": N|null}}}}}`. One reader (`observed_limits(provider, model_id)`) and one
  writer (`record_observed_models(spec, probe)`), both in `core/provider.py`. Written at
  `register_provider` (so `setup provider add` records what the registration probe saw) and by
  `refresh_observed_models_due()`: for every provider whose catalog scope is `global` (operator
  registered; never an unregistered built-in, so a test home with no document opens no socket)
  whose `observedAt` is not today, probe once and record. `serve.py::_run_sweeps` calls it under
  `contextlib.suppress(Exception)` only when `dispatch` is set. D-57: no migration, no fallback
  reader for any other shape.
- **Templates.** Delete the two `contextWindow`/`maxTokens` rows in
  `templates/providers/01-anthropic.yaml`; `rg 'contextWindow|maxTokens'
  src/docket/templates/providers` prints nothing. Leave every `price`, `pricesAsOf`, `presets`.
- **`provider add` (`cli/_setup_model.py`).** `--ctx`/`--max-tokens` lose their defaults
  (`_DEFAULT_CTX` 16384 / `_DEFAULT_MAX_TOKENS` 8192 are filled-in numbers the operator never
  stated); absent means "take what the probe observes, else unknown". A given value is declared.
  `_build_spec` follows. If a golden case passes `--ctx`, nothing changes for it; do not
  regenerate a golden unless its printed text changes for this reason and explain the diff.
- **Sources printed.** `setup provider show <name>` prints one row per model with `window` and
  `output`, each as `<N> (declared)`, `<N> (observed <date>)` or `unknown`; `--json` carries
  `contextWindow`, `maxTokens`, `limitsSource` (`declared` | `observed` | `unknown`) and
  `observedAt`. `core/pod_report.py::_provider_report`'s `model` block replaces `"source": "row"
  | "none"` with the same `source` values (D-57; update its tests and model-profiles "Provider
  catalog" 7). `ModelReadiness.context_window`/`max_output` are the resolved values.
- **Agent loop (`core/agent_loop.py`).** No change to `_resolve_context_bounds`'s arithmetic:
  a known output cap (declared or observed) is already sent as `max_tokens`. `agent-loop.spec.md`
  1.42.0 says the reserve is budget arithmetic only and that an endpoint whose cap is unknown
  sends no `max_tokens`, so the provider's own default applies and is reported as `unknown`,
  never as 4,096.
- **Rides along (same files).** `edges/adapters/llm.py::request_part_bytes` measures the UTF-8
  encoding (`len(json.dumps(part).encode("utf-8"))`), not `len(str)` (18,037 B against 11,367 B
  measured for a non-ASCII part); `TokenUsage` gains `cache_write_tokens` (from
  `cache_creation_input_tokens` and `prompt_tokens_details.cache_write_tokens`, whichever the
  body carries, 0 otherwise) and `_trace_llm_call` writes `cacheWriteTokens` only when it is
  positive (`trace-store.spec.md` 1.13.0, additive to requirement 28's record; the 1.25.0
  reference in its text is the loop spec's, leave it).
- **Non-goals.** Refusing an unadvertised step `model:`; prices from the provider; a change to
  `AGENT_LOOP_TOKEN_BUDGET` or to any `task["maxTokens"]` path; a listing cache for MCP.
- **Tests.** `tests/unit/edges/adapters/test_llm.py` (one test per fixture body; the zero
  gateway row is unknown; `n_ctx_train` is never read; UTF-8 bytes), `tests/unit/core/
  test_provider.py` (store shape, precedence declared > observed > unknown, a never-observed
  model is unknown, `refresh_observed_models_due` skips a provider observed today and skips
  built-ins), `tests/unit/cli/test__setup_model.py` (show prints the three source forms; add
  without `--ctx` records the observed window), the `_provider_report` test, a `_run_sweeps`
  test that the refresh is called only with `dispatch`. Monkeypatch `probe_models`/`probe_spec`
  everywhere; never open a socket in a unit test.
- **Docs you may edit.** `docs/MODEL-GATEWAYS.md` (the `models[]` sentence near line 69) and
  `docs/CONFIGURATION.md` (the `--ctx`/`--max-tokens` sentences near lines 229-250 and the
  `docket-providers.json` row near line 1147; add a `provider-models.json` row to the same
  table). `docs/commands.md` is regenerated with `scripts/gen_cli_docs.py` (no `--check`) if the
  help text changed. `README.md` line 91 keeps its explicit `--ctx`.
- **Acceptance (the card's).** The four recorded bodies yield the published limits and the
  llama.cpp window is 32768; the templates grep prints nothing; a never-observed model shows
  `unknown`, never a filled-in number; `setup provider show` names every limit's source.
- **Return.** The worker return shape, plus: the evidence citation for the 4,096 cut, the
  CHANGELOG lines (Added: observed limits + `provider-models.json` + sources printed; Changed:
  templates lose limit rows, `provider add` defaults, `pod report` source values; Fixed: UTF-8
  request bytes, `cacheWriteTokens`), and any golden you had to touch with the line-by-line
  reason.
