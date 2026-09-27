# Wave 56–58 worker packets — Phase 32, observability as configuration (D-48)

Coordinator: the session that planned Phase 32 on 2026-09-27 and activated it the same day.
**Base commit for Wave 56: the commit that opened it on `main`**
(`git log -1 --format=%h -- .agents/handoffs/wave-56-worker-packets.md`; Phase 31 closed at
`3f39484`, the README follow-up is `0191ffe`). Wave 57 bases on the Wave 56 rollup, Wave 58 on
the Wave 57 rollup; Wave 59 is integrator-only. One card, one Sonnet worker, one isolated
worktree each. Decision, the rules, the destination table and the verdict table:
[docs/adr/0014-observability-export.md](../../docs/adr/0014-observability-export.md).
The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P32-<N>`) is the
contract; this file is the map. Read §0 and your own packet only.

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 56 | P32-1, P32-2 | P32-1, P32-2 |
| 57 | P32-3, P32-4, P32-5 | P32-4, P32-5, P32-3 |
| 58 | P32-6, P32-7, P32-8 | P32-6, P32-7, P32-8 |
| 59 | P32-9 (integrator) | — |

## 0. Rules for every worker

- **Isolation.** One branch `p32-<N>-<slug>` in your own worktree, checked out at the wave's
  base (**verify with `git merge-base HEAD origin/main`**: every Phase 31 worktree was created at
  a stale commit and had to be re-based first). Never touch `~/.docket`: every CLI run sets
  `export W=$(mktemp -d); export DOCKET_HOME=$W/.docket` (two statements: in one `export`, `$W`
  is still empty; **never override `HOME`**: it breaks uv's cache). pytest isolates `DOCKET_HOME`
  through the autouse fixture in `tests/conftest.py`. **Never call a real model endpoint and
  never probe a real vendor host** (`cloud.langfuse.com`, `api.honeycomb.io`, anything not
  `127.0.0.1`): every HTTP target in a test is a local `http.server` the test starts on port 0
  and stops in `finally`. The fake backend in `tests/integration/test_docket_driver.py` and the
  fake driver in `tests/integration/test_dispatch.py` are the patterns.
- **Never `git stash`.** Set work aside with a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`; run `env -u VIRTUAL_ENV uv sync --extra mcp`
  once in your worktree first (`scripts/gen_cli_docs.py` imports `click`).
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Amend (or
  create) the spec requirement text and add the pre-assigned version + changelog line (newest
  first). A new spec copies the header block of `specs/functional/session-history.spec.md`
  (Version, Status, Last Updated, Purpose, Scope, Requirements, Interface Contracts, Examples,
  Validation, Changelog) and must pass `bash scripts/validate-specs.sh`; you do **not** edit
  `specs/README.md` (integrator). 3. Write the RED test and see it fail on the base for the
  stated reason. 4. Smallest implementation. 5. Gates.
- **Test rule (ADR 0014).** One RED behavioural test in the module's existing `SUBJECT` file (or
  the file the card names); a second only for the card's fail-closed negative case. Existing
  tests, goldens and specs are the no-change oracle. No agent-lane tests, no guards, no new test
  files unless the card names one. Docstrings at most three lines; no card ids, wave numbers or
  dates in any `.py` or `.yaml` file (`scripts/maint/comment_lint.py --check` refuses them).
- **Nothing leaves the host by default.** `payload: metadata` is the default everywhere; a
  test that asserts `full` also asserts `metadata` drops `arguments`. A present credential never
  activates an exporter. A credential **value** never enters a document, a fixture, a template,
  a test string or an error message; credential **names** (`LANGFUSE_SECRET_KEY`) are fine. The
  scrub step greps the diff for `sk-`, `pk-lf-`, `sk-lf-`, `/home/`, `@gmail`.
- **No new dependency.** `pyproject.toml` is forbidden. OTLP JSON is hand-encoded over stdlib
  `urllib`/`json`, like `edges/adapters/llm.py` encodes chat completions. If you believe the
  card cannot be done without a package, stop and return the contention.
- **Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never
  prints, never opens a socket, never imports `edges/` (`core/telemetry.py` receives a
  `SpanSink` object; it never constructs one). Docket-owned JSON only through `edges/store.py`
  (`exporters-health.json` included); JSONL appends in `core/trace.py` are the D-12 exemption.
  Every tool call through `core/tools.py::dispatch_tool` (untouched in this phase).
- **Never conflate an estimate with a measurement.** `TokenUsage` is measured; `cost_usd` on the
  driver is `0.0` by design; no card writes a dollar figure into a record, a span or an
  attribute. `llm_call` has no `cost_usd`.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `pyproject.toml`, `docs/` except
  `docs/commands.md` and `docs/contracts/config-v1/*.schema.json` regeneration
  (`scripts/gen_cli_docs.py`, `scripts/gen_config_schemas.py`). Return the
  README/CHANGELOG/CONFIGURATION line you would add instead of writing it. Never edit
  `scripts/metrics.py` or `scripts/validate-specs.sh`. Never touch `core/tools.py`,
  `core/policy.py`, `core/security.py`, `core/audit.py`, `core/session.py`, `serve.py`,
  `core/provider.py`, `edges/adapters/llm.py` (except P32-1's `complete`), `core/agent_loop.py`
  (except P32-1's and P32-3's named lines), `core/dispatch.py` (except P32-3's one line).
- **Goldens.** `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` stays byte-identical
  unless your packet names a case; then regenerate only that case and list every changed line
  with its reason.
- **Worker gates** before returning:

  ```bash
  env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src
  env -u VIRTUAL_ENV uv run pytest -q
  env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
  bash scripts/validate-specs.sh
  env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check
  env -u VIRTUAL_ENV uv run python scripts/gen_config_schemas.py --check
  env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <every .py you touched>
  env -u VIRTUAL_ENV uv run pytest -q tests/guards
  ```

  `scripts/metrics.py --check` is expected to fail on a branch that adds tests or a spec; say
  so. The function-span ratchet (`tests/guards/test_function_span.py`, 150 lines) refuses a new
  function over the limit and `cli/__init__.py::cmd_pod` sits exactly at it: never add a line
  there. `tests/guards/test_no_print_in_core_edges.py` and `test_no_subprocess_in_core.py` apply
  to every new module. `tests/guards/test_layout.py` may need its baseline **shrunk**, never
  widened, when a new package appears; say what changed.
- **Commit.** One commit per card. Subject `Type: description` (`Add:`/`Fix:`/`Docs:`), ASCII,
  body says what was false and what is now true. **No AI mention, no `Co-Authored-By` trailer of
  any kind.** Before committing: `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-|pk-lf-'`
  prints nothing (`task-`/`risk-` are false positives for `sk-`; a real key is not). Do not
  push, do not merge into `main`.
- **Return** a delta of 1,500–3,000 characters, no logs: card / branch / commit; outcome;
  user-visible behaviour; changed paths and owned functions; spec sections + one changelog line
  per spec; README/CHANGELOG/CONFIGURATION lines for the integrator; RED evidence (test id, base
  failure reason); focused tests -> result; worker gates -> pass or first failing gate; goldens
  changed; missing/failed; pending in this card; later follow-ups (locators only); contention
  note (which other card in your wave touches a neighbouring symbol, and that you did not).

Symbols below were located at `0191ffe` and drift; re-locate every one with `rg -n` before editing.

## P32-1 — the model call is a trace event (Wave 56)

Branch `p32-1-llm-call-event`. Specs: **new** `specs/functional/trace-store.spec.md` 1.0.0,
`agent-loop.spec.md` -> 1.25.0, `harness-mode.spec.md` -> 1.1.2 (exact rule text in the card).

- **Where.** `core/llm.py::ChatResponse` (three fields, defaults, docstring stays ≤ 3 lines);
  `edges/adapters/llm.py::OpenAIChatClient.complete` (`time.perf_counter()` before building the
  request; fill `model=self.endpoint.model_id`, `provider=self.endpoint.provider`, `latency_ms`
  on **every** `return ChatResponse(...)` — count them first: `rg -n "return ChatResponse" src/docket/edges/adapters/llm.py`);
  `core/agent_loop.py`: new `_trace_llm_call` placed right after `_trace_tool_result`, called at
  the top of `_TurnState.call_backend_and_handle_response` after `response = self.backend.complete(...)`
  and before the first `if`, and once in `_TurnState.summarize_without_reentry` with
  `purpose="compaction"`; `core/trace.py::EVENT_TYPES` one entry with a one-line comment like its
  neighbours; `cli/_trace.py::_render_event` + the colour dict.
- **The trace-store spec** is new: it *documents what exists* in `core/trace.py` (record shape,
  `EVENT_TYPES` in full, `redact`, `subscribe`, `trace_ingest`, `expire_old_traces`,
  `DOCKET_NO_TRACE`, the three `TraceStatus` outcomes) plus your `llm_call`. Move nothing out of
  `pod-dispatch.spec.md`/`serve-read-api.spec.md`/`harness-mode.spec.md`; cross-reference them.
  Status "Implemented and live". Keep it under 250 lines.
- **RED.** `tests/integration/test_agent_loop.py` (`rg -n "SUBJECT" tests/integration/test_agent_loop.py`;
  add a class `TestLlmCallTrace` with the two-records case and the failed-second-call case) and
  `tests/integration/test_llm_port.py` (the existing `OpenAIChatClient` file; the latency
  case with a local `http.server` that sleeps 50 ms; the closed-port case).
- **Contention.** P32-2 owns `core/telemetry.py` and `tests/fixtures/traces/`; it reads your
  payload key names from the card, not from your branch. Nothing else in Wave 56 touches your
  files. Do not add `task_id` (P32-3, next wave).

## P32-2 — a neutral span model and the projection (Wave 56)

Branch `p32-2-span-model`. Spec: **new** `specs/functional/observability-export.spec.md` 1.0.0
(sections "Span model", "Projection", "Export policy"; Status "Draft — model and projection
implemented; no exporter yet"; write the Purpose/Scope so P32-4/5/6/7 can add sections without
rewriting yours: name them as planned sections).

- **Where.** `core/telemetry.py` (new). Imports: `dataclasses`, `hashlib`, `datetime`, `typing`,
  `docket.core.trace` (for `EVENT_TYPES` only). Keep every function under 60 lines; `project`
  dispatches on `event_type` through a dict of small handlers, not one `if` ladder. Timestamps
  are the record's ISO `ts` strings; `Span.start_ts`/`end_ts` stay ISO (the wire converts to
  nanoseconds in P32-5). `llm_call` start = `ts − duration_ms` computed with `datetime`.
- **Fixture.** `tests/fixtures/traces/dispatch-3-hops.jsonl`: one session, hand-written to the
  record shape in `core/trace.py::trace_event` (`ts, project, session_id, agent_role,
  event_type, payload`, optional `duration_ms`), `llm_call` payload keys exactly as P32-1's card
  lists them (`model, provider, ok, finishReason, failureKind, inputTokens, outputTokens,
  cachedTokens, iteration`), `tool_call` payload `{"tool": "read", "callId": "c1", "arguments":
  {...}}`, `tool_result` payload `{"tool": "read", "callId": "c1", "ok": true, "output": "..."}`.
  Generic paths only; no real names.
- **RED.** `tests/unit/core/test_telemetry.py` (new; `SUBJECT = docket.core.telemetry`): the
  fixture projection case; the `EVENT_TYPES` coverage case (parametrize over
  `sorted(EVENT_TYPES)`); the `metadata` negative.
- **Contention.** P32-1 owns `core/trace.py` (one line) and `core/agent_loop.py`; you import
  `EVENT_TYPES` unchanged. Do not create `Pipeline` or any thread (P32-6).

## P32-3 — `task_id` on the record; ingest through the seam (Wave 57)

Branch `p32-3-task-id`. Base: the Wave 56 rollup. Specs: `trace-store.spec.md` -> 1.1.0,
`pod-dispatch.spec.md` -> 6.23.0, `serve-read-api.spec.md` -> 2.13.2.

- **Where.** `core/trace.py::trace_event` (keyword-only `task_id: str = ""`, written only when
  truthy, placed after `event_type` in the record so readers see it early) and `::trace_ingest`
  (call `_notify_subscribers(r)` for each record right before `_append(tracefile, records)`; the
  synthetic `session_end` too); `core/agent_loop.py::run_agent_turn` (`trace_task_id: str = ""`),
  `_TurnState` (one field), every `_trace_*` helper (one parameter, passed through — including
  P32-1's `_trace_llm_call`); `edges/adapters/docket_runtime.py::run_turn` (`trace_task_id:
  str | None = None`, forwarded next to `trace_session_key`); `core/dispatch.py`: the single
  call `driver.run_turn(... trace_project=ctx.project, trace_session_key=ctx.session_id ...)`
  gains `trace_task_id=ctx.task_id` (`rg -n "trace_session_key=ctx" src/docket/core/dispatch.py`).
- **RED.** `tests/integration/test_dispatch.py` (the hop's records carry `task_id`; fails: key
  absent) and `tests/unit/core/test_trace.py` (`class TestIngestNotifiesSubscribers`; fails:
  the sink list stays empty).
- **Contention.** P32-4 owns `core/exporter.py`, `config.py`, `core/config_docs.py`; P32-5 owns
  `edges/adapters/exporters/`. None of them touches your files. Merge order puts you last in
  the wave because `core/agent_loop.py` is the hot file.

## P32-4 — `kind: exporter` (Wave 57)

Branch `p32-4-exporter-kind`. Base: the Wave 56 rollup. Specs: `observability-export.spec.md`
-> 1.1.0, `config-format.spec.md` -> 1.4.0, `workspace-structure.spec.md` -> 1.15.0.

- **Where.** `core/exporter.py` (new): start from `core/provider.py` — copy the shape of
  `AuthSpec`, `ProviderSpec`, `load_provider_document`, `Catalog`, `_load_builtin_providers`,
  `_load_global_providers`, `save_provider`, `delete_provider`, `resolve_credential`,
  `_with_inherited_identity`, `verify_endpoint`, `export_provider`; rename, drop models/prices/
  presets, add `resource`/`aliases`/`events`/`payload`/`payloadMaxChars`/`enabled`, add
  `basic` (two credential names, ordered). Do **not** refactor `core/provider.py` to share code:
  the integrator measures the duplication after merge and decides (ADR 0014 lists it as a
  follow-up, not a card). `config.py`: the five constants beside `PROVIDERS_FILE` /
  `PROVIDER_TEMPLATES_DIR` and `no_export()` beside `no_trace()`. `core/config_docs.py::KINDS`
  + `_MODEL_FOR_KIND`; check `cli/_validate.py` needs no change (it dispatches on
  `load_document`); run `scripts/gen_config_schemas.py` (both copies). Templates under
  `src/docket/templates/exporters/` with the `NN-<name>.yaml` naming of `templates/providers/`;
  each has a `note` a newcomer can act on; `01-otel-collector.yaml` is the only one with
  `payload: full`. Check the wheel ships them the way `tests/agent/release/test_recipe_artifacts.py`
  checks recipes (do not add an agent-lane test; return the locator if a release test should
  cover them).
- **RED.** `tests/unit/core/test_exporter.py` (new; `SUBJECT = docket.core.exporter`): the
  catalog + `activation_state` case; the inherited-identity case; the three refusals.
- **Contention.** P32-5 owns `edges/adapters/exporters/`; P32-3 owns `core/trace.py`,
  `core/agent_loop.py`, `docket_runtime.py`. Your `ProbeResult` is your own dataclass so you
  import nothing from `edges/`.

## P32-5 — the `otlp-http` dialect (Wave 57)

Branch `p32-5-otlp-http`. Base: the Wave 56 rollup. Spec: `observability-export.spec.md`
-> 1.2.0 (section "The otlp-http dialect").

- **Where.** `edges/adapters/exporters/__init__.py` (package docstring only) and
  `edges/adapters/exporters/otlp_http.py` (new). Model it on `edges/adapters/llm.py::
  OpenAIChatClient.complete` for the `urllib` request/`HTTPError`/`URLError` handling and on
  `probe_models` for the probe. Nanoseconds: `int(datetime.fromisoformat(ts).timestamp() * 1e9)`
  rendered as `str`. Integers in OTLP JSON attribute values are strings (`{"intValue": "42"}`);
  ids are lowercase hex strings; enums are numbers. Inject `clock`/`sleep`/`opener` so the retry
  test never sleeps for real. The docket version comes from `docket.__version__`
  (`rg -n "__version__" src/docket/__init__.py`).
- **Fixture.** `tests/fixtures/otlp-v1/dispatch-3-hops.json` = `encode()` of the projection of
  P32-2's JSONL fixture (on your base after the rollup) with `resource={"service.name":
  "docket"}` and `aliases={"session.id": "langfuse.session.id"}`, written with
  `json.dumps(sort_keys=True, indent=2) + "\n"`. The test regenerates and compares; a diff is a
  failure, never a reason to rewrite the fixture silently.
- **RED.** `tests/unit/edges/test_otlp_http.py` (new; `SUBJECT =
  docket.edges.adapters.exporters.otlp_http`): the golden case; the basic-auth POST case; the
  429-then-200 case; the closed-port case.
- **Contention.** P32-4 owns `core/exporter.py`; you do **not** import `ExporterSpec` (P32-6's
  `sink_for` maps a spec to your constructor next wave). P32-3 owns `core/trace.py`.

## P32-6 — the pipeline, wired where turns run (Wave 58)

Branch `p32-6-pipeline-wiring`. Base: the Wave 57 rollup. Specs: `observability-export.spec.md`
-> 1.3.0, `agent-loop.spec.md` -> 1.26.0.

- **Where.** `core/telemetry.py`: `SpanSink` Protocol, `SinkResult` (the dataclass P32-5
  returns — define the Protocol against its field names), `PipelineStats`, `Pipeline`, and the
  module-level `start`/`flush`/`close`/`health` with one `_REGISTRY` guarded by a lock; the
  worker thread pattern is `edges/adapters/toolbox.py`'s `_drain` reader (daemon thread, join
  with timeout). `core/trace.py::add_subscriber(sink) -> Callable[[], None]` next to `subscribe`
  (same `_SUBSCRIBERS_LOCK`; `subscribe` may be re-expressed over it, behaviour identical).
  `edges/adapters/exporters/__init__.py`: `_DIALECTS` and `sink_for(spec, values)` (build the
  auth header pair here: `bearer` → `("Authorization", f"Bearer {v}")`, `basic` →
  base64 of `user:pass`, `header` → `(spec.auth.header, v)`, `none` → `None`).
  `edges/adapters/docket_runtime.py::run_turn`: the lazy `start` before the turn; wrap the turn
  in `try/finally` so `flush` + the health write run on every path; `store.write_json(...)`; `atexit.register` once
  at module import. `packages/docket-runtime/hatch_build.py`: find how `core/skills.py` was
  added (`rg -n "skills" packages/docket-runtime/`) and add the three new paths the same way.
- **RED.** `tests/integration/test_otlp_export.py` (new; `SUBJECT` importable): the real-POST
  case, the never-answers negative (time both runs in the test with `time.perf_counter`), the
  zero-exporters case, the `DOCKET_NO_EXPORT` case.
- **Contention.** P32-7 owns `cli/` and `core/exporter.py::enable_exporter`/`disable_exporter`;
  you only **import** `load_enabled_exporters`, `resolve_credentials`, `read_health`. P32-8 owns
  `core/pod_apply.py`. `serve.py` and `cli/_harness.py` are untouched: both reach `run_turn`.

## P32-7 — `docket exporters` (Wave 58)

Branch `p32-7-exporters-cli`. Base: the Wave 57 rollup. Specs: `observability-export.spec.md`
-> 1.4.0, `cli-interface.spec.md` -> 1.54.0, `cli-json-shapes.spec.md` -> 1.15.0.

- **Where.** `cli/_keys.py`: extract `prompt_and_store(name) -> bool` from `_keys_add` (the
  `getpass` call, the format warning, `_save_secrets`, `_touch_secrets_meta`); `_keys_add`'s
  output stays byte-identical (a golden may pin it: `rg -ln "keys" tests/golden/cases`).
  `cli/_exporters.py` (new): copy `cli/_provider.py`'s `run_provider`/`_parse_opts`/`_run_*`
  layout; `enable` = credentials → probe → `verify_endpoint` → `enable_exporter` → audit →
  print; the probe goes through `edges.adapters.exporters.otlp_http.probe` selected by dialect
  (a tiny `_probe_for(spec)` in `cli/_exporters.py`, or in `edges/adapters/exporters/__init__.py`
  if P32-6's `sink_for` is already on your base — check; if not, keep it in `cli/`). Register
  in `cli/__init__.py` exactly as `cmd_recipes` (`rg -n "def cmd_recipes" -B 6 src/docket/cli/__init__.py`).
  `core/exporter.py`: `enable_exporter(name, overrides) -> ExporterSpec` (writes the minimal
  global entry through `save_exporter`; refuses an unknown name) and `disable_exporter(name)`;
  nothing else in that module. `cli/_config.py::_explain`: the `exporters` key built from
  `load_catalog()`, `activation_state`, `read_health()`; the human renderer line beside the
  provider line. `cli/_doctor.py::_check_exporters` registered where `_check_provider_coverage`
  is called. `completions` golden: one line; `docs/commands.md` regenerated.
- **RED.** `tests/integration/test_exporters_cli.py` (new): the no-TTY negative (set
  `sys.stdin` to a non-tty via `monkeypatch`), the enable-with-local-server case, the built-in
  `remove` refusal; `config explain --json` and `doctor` assertions ride in the same file.
- **Contention.** P32-6 owns `core/telemetry.py`, `docket_runtime.py`, `edges/adapters/
  exporters/__init__.py`; P32-8 owns `core/pod_apply.py`, `cli/_pod.py`, `cli/_recipes.py`.
  `cli/__init__.py::cmd_pod` is at the span limit: never add a line there.

## P32-8 — a recipe names its destinations (Wave 58)

Branch `p32-8-recipe-exporters`. Base: the Wave 57 rollup. Specs: `pod-blueprints.spec.md`
-> 1.20.0, `config-format.spec.md` -> 1.5.0, `cli-interface.spec.md` -> 1.55.0.

- **Where.** `core/pod_apply.py`: `_MANIFEST_KEYS` + the type check in `plan_apply` (each name
  must be a `str` matching the exporter name regex and present in
  `core.exporter.load_catalog()`; import `core.exporter` at module level, it imports nothing
  from `edges/`); `RecipeSummary.exporters` + `render()`; `_export_manifest` writes the recorded
  list; `apply` returns the names so the CLI renders state (add a field to the existing result
  type rather than printing from `core/`). `core/pod.py::PodSettings`: one recorded key
  `exporters` in `RECORDED_KEYS` (`rg -n "RECORDED_KEYS" src/docket/core/pod.py`), refused by
  `config set` like `configSource`. `core/config_docs.py::PodDocument.exporters`; both schema
  copies. `cli/_pod.py`: the shared header/plan renderer P31-1 extracted (`rg -n "def render_apply"
  src/docket/cli/_pod.py`) gains the state lines from `core.exporter.activation_state`;
  `cli/_recipes.py::show` prints the same lines. `docket recipes list` columns unchanged.
- **RED.** `tests/unit/core/test_pod_apply.py` (`class TestRecipeExporters`: the summary/apply
  case with no keys stored; the two refusals).
- **Contention.** P32-7 owns `cli/_exporters.py`, `cli/_config.py`, `cli/_doctor.py`,
  `core/exporter.py::enable_exporter`; you call `activation_state` and `load_catalog` (P32-4,
  on your base) only. Do not edit any shipped recipe.

## P32-9 — integrator (Wave 59)

Docs, the external verification with real credentials on this machine, the real fixture
capture, the README sentence, the archive. Not a worker packet; the card is the checklist.
