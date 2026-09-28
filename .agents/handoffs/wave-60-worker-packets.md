# Wave 60–63 worker packets — Phase 33, export privacy levels (D-49)

Coordinator: the session that planned Phase 33 on 2026-09-28.
**Base commit for Wave 60: the commit that opened it on `main`**
(`git log -1 --format=%h -- .agents/handoffs/wave-60-worker-packets.md`; Phase 32 closed at
`5f53e52`, the Langfuse follow-up is `940c3cd`). Wave 61 bases on the Wave 60 rollup, Wave 62 on
the Wave 61 rollup; Wave 63 is integrator-only. One card, one Sonnet worker, one isolated
worktree each. Decision, the class and level tables, the rules and the verdict table:
[docs/adr/0015-export-privacy-levels.md](../../docs/adr/0015-export-privacy-levels.md).
The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P33-<N>`) is the
contract; this file is the map. Read §0 and your own packet only.

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 60 | P33-1 | P33-1 |
| 61 | P33-2, P33-3 | P33-2, P33-3 |
| 62 | P33-4, P33-5 | P33-4, P33-5 |
| 63 | P33-6 (integrator) | — |

## 0. Rules for every worker

- **Isolation.** One branch `p33-<N>-<slug>` in your own worktree, checked out at the wave's
  base (**verify with `git merge-base HEAD origin/main`**: every Phase 31 and 32 worktree was
  created at a stale commit and had to be re-based first). Never touch `~/.docket`: every CLI run sets
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
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Add your
  requirements under **your own new section heading, numbered in your pre-assigned range** (the
  card names it). **Do not touch `**Version**`, `**Status**`, `**Last Updated**` or the
  changelog** — the integrator bumps each spec once per rollup (three Phase 32 merges conflicted
  on exactly that). A new spec copies the header block of `specs/functional/session-history.spec.md`
  (Version, Status, Last Updated, Purpose, Scope, Requirements, Interface Contracts, Examples,
  Validation, Changelog) and must pass `bash scripts/validate-specs.sh`; you do **not** edit
  `specs/README.md` (integrator). 3. Write the RED test and see it fail on the base for the
  stated reason. 4. Smallest implementation. 5. Gates.
- **Test rule (ADR 0015).** One RED behavioural test in the module's existing `SUBJECT` file (or
  the file the card names); a second only for the card's fail-closed negative case. Existing
  tests, goldens and specs are the no-change oracle. No agent-lane tests, no guards, no new test
  files unless the card names one. Docstrings at most three lines; no card ids, wave numbers or
  dates in any `.py` or `.yaml` file (`scripts/maint/comment_lint.py --check` refuses them).
- **Nothing leaves the host by default.** `minimal` is the default everywhere and every
  migration or default only narrows; a test that asserts a class is shared also asserts
  `minimal` does not share it (the canary oracle). A present credential never
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
  `core/provider.py`, `edges/adapters/llm.py`, `core/trace.py`, `core/approval.py`,
  `core/runs.py`, `core/dispatch.py`, `core/agent_loop.py` (except P33-3's `_trace_llm_call`
  and its two call lines), `edges/adapters/exporters/` (the wire does not change).
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

Symbols below were located at `940c3cd` and drift; re-locate every one with `rg -n` before editing.

## P33-1 — classes, levels, the allowlist projection (Wave 60)

Branch `p33-1-privacy-allowlist`. Spec: `observability-export.spec.md`, new sections "Privacy
classes and levels" and "Allowlist projection", requirements **64–79**; amend 11, 16 and 17 in
place to say what they now mean (16/17 describe `admit` filtering by event only).

- **Where.** New `core/privacy.py` (pure data + `resolve` + `describe`; it must not import
  `core/telemetry.py` or `core/exporter.py`: `telemetry` already imports `exporter`, and both
  need the levels). In `core/telemetry.py`: `ExportPolicy`, `project`, `_new_root`, every
  `_handle_*`, the new `ATTRIBUTE_CLASSES`/`_STRUCTURAL_KEYS`/`_granted`, `capture_classes`,
  and exactly one line in `start` (the `ExportPolicy(...)` call → `classes=frozenset()`,
  `label="minimal"`). `Pipeline.offer` passes its policy to `project`.
- **Structural keys.** Build `_STRUCTURAL_KEYS` from the real call sites, not from memory:
  `rg -n "trace_event\(|_emit_trace\(|_trace_locked\(" src/docket` and read each payload.
  Note the name collision: `guardrail_*`'s `action` is a verdict (structure), `approval_requested`'s
  `action` is a command line (`toolArguments`) — per event type, never per key name.
- **RED.** The canary case in `tests/unit/core/test_telemetry.py` (one class; parametrise over
  levels and single-class shares). Build the synthetic records from `core.trace.EVENT_TYPES` so a
  future event type is covered automatically. Oracle: substring search over
  `json.dumps(otlp_http.encode(...))` — importing `edges/adapters/exporters/otlp_http` from a
  test is fine; importing it from `core/` is not.
- **Golden.** `tests/fixtures/otlp-v1/dispatch-3-hops.json` changes by exactly two root
  attributes; regenerate it through the existing test's own encode call and list the diff. The
  trace fixture is untouched.
- **Contention.** None in Wave 60. P33-3 (next wave) writes `inputMessages`/`outputMessages`/
  `systemInstructions`/`systemInstructionsSha256` into `llm_call`; read those exact names from the
  card, and read them defensively (absent today).

## P33-2 — the exporter document declares its privacy (Wave 61)

Branch `p33-2-exporter-privacy`. Specs: `observability-export.spec.md` requirements **80–87**
under a new "Exporter privacy fields" section (and strike `payload` from "Exporter documents");
`config-format.spec.md` exporter fields.

- **Where.** `core/exporter.py::ExporterSpec` (fields, validator, `privacy_label`,
  `privacy_classes`, `legacy_fields`), the audit detail strings in `enable_exporter`/
  `disable_exporter`/add; `core/telemetry.py::start` (the constructor call only);
  `src/docket/templates/exporters/*.yaml`; schemas via `scripts/gen_config_schemas.py`; the
  `spec.payload` readers: `rg -n "\.payload\b|payload_max_chars" src/docket`.
- **Legacy.** `model_config` ignores unknown keys today, so `payload` would vanish silently —
  capture it in a `model_validator(mode="before")` into `legacy_fields`; it never maps to a wider
  level.
- **RED.** The `privacy: actions` case in `tests/integration/test_otlp_export.py` (the file's
  fake backend + local `http.server` sink). Keep a `minimal` twin of it as the negative.
- **Contention.** P33-3 runs in parallel on `core/agent_loop.py` and `cli/_trace.py`; you touch
  neither. `cli/_exporters.py`: only the lines that read `payload` (P33-4 rebuilds that UX next
  wave — no new output wording beyond `privacy: <label>` where `payload: <x>` was).

## P33-3 — the model call records its content on demand (Wave 61)

Branch `p33-3-llm-content-capture`. Specs: `trace-store.spec.md` new section "Captured content";
`agent-loop.spec.md` "Tracing" amended; `harness-mode.spec.md` one additive note on the event row.

- **Where.** `core/agent_loop.py::_trace_llm_call` (new keyword `messages`), its two call lines
  (`_TurnState.call_backend_and_handle_response` and the compaction summarizer — pass the exact
  list handed to `backend.complete`), one module-level helper that turns `ChatMessage`s into the
  OTel `{"role", "parts"}` shape; `cli/_trace.py::_render_event` (the `llm_call` branch only).
  Call `core.telemetry.capture_classes()` once per `_trace_llm_call`; keep the per-trace-key
  last-instructions hash in module state keyed by `trace_key`.
- **Byte-identical rule.** With an empty grant, build the payload dict exactly as today — same
  keys, same insertion order — so `json.dumps` is unchanged. Add a test that compares against a
  record produced with the capture path disabled, not against a hand-written string.
- **Redaction.** Do not redact in `agent_loop`; `trace_event` already runs `redact` on the whole
  payload. Assert it in the test with a secret-shaped string in a tool result.
- **RED.** `TestLlmCallTrace` in `tests/integration/test_agent_loop.py`, monkeypatching
  `core.telemetry.capture_classes`.
- **Contention.** P33-2 runs in parallel on `core/exporter.py`, `core/telemetry.py::start`, the
  templates and the `payload` readers in `cli/`; you touch none of them. Never edit
  `core/telemetry.py`.

## P33-4 — the privacy command, confirmation, disclosure (Wave 62)

Branch `p33-4-privacy-command`. Specs: `observability-export.spec.md` requirements **88–97**
("Privacy commands and disclosure"); `cli-interface.spec.md`; `cli-json-shapes.spec.md`
(`config explain --json` exporters entries gain `privacy: {label, classes}`).

- **Where.** `core/exporter.py::set_privacy`/`is_widening` (new, beside `enable_exporter`,
  same minimal-override writer); `cli/_exporters.py` (`_run_list`, `_run_show`, `_run_enable`,
  `_run_add`, new `_run_privacy`, one handler entry + usage line); `cli/__init__.py` (the
  exporters help text only — `cmd_pod` is at the span limit, do not add lines there);
  `cli/_config.py::_explain`; `cli/_doctor.py::_check_exporters`.
- **TTY.** Use the same `sys.stdin.isatty()` test `_run_enable` already uses before
  prompting for a credential; do not invent another. Tests drive the non-TTY path through `CliRunner`/subprocess
  and the TTY path by monkeypatching that check plus `input`.
- **Golden.** `exporters list` (`tests/golden/cases/readonly/exporters_list.golden`) gains the
  `SHARES` column; regenerate with `bash tests/golden/run.sh capture exporters list` and list
  every changed line.
- **Contention.** P33-5 adds `_run_preview` in a new module and one handler entry + usage line in
  the same `run_exporters` — leave that entry to P33-5; the integrator reconciles the two dict
  lines and the help text. Regenerate `docs/commands.md` on your branch; the integrator
  regenerates after both merge.

## P33-5 — preview (Wave 62)

Branch `p33-5-exporters-preview`. Specs: `observability-export.spec.md` requirements **98–101**
("Preview"); `cli-interface.spec.md`.

- **Where.** New `cli/_exporters_preview.py`; one handler entry + usage line in
  `cli/_exporters.py::run_exporters`. Project with `core.telemetry.project`/`flush_open` and a
  fresh `ProjectionState`, the exporter's own `ExportPolicy` built the way `start` builds it
  (factor nothing out of `start`; read its fields), encode with
  `edges.adapters.exporters.otlp_http.encode` (cli may import edges). Newest session:
  the newest `*.jsonl` under `config.TRACES_DIR` by mtime across projects.
- **No side effects.** No socket, no write, no audit, no health file: assert all three files'
  bytes before and after in the test.
- **RED.** A new class in `tests/integration/test_exporters_cli.py` with the minimal/actions
  canary pair.
- **Contention.** P33-4 owns every other function in `cli/_exporters.py` and the exporters help
  text; you add one dict entry and one usage line only.

## P33-6 — integrator (Wave 63)

The card is the contract. The seam test (real `_trace_llm_call` into the real projection) goes
in `tests/integration/test_otlp_export.py`. Live proof: one dispatch per level (`minimal`,
`actions`, `conversation`) against the local collector and Langfuse, a canary in the delegated
task and in a file the agent reads; `docket exporters preview` before each; record what arrived.
