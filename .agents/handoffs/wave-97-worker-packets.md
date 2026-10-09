# Wave 97 worker packets — the live-run triage cards B–E (no phase)

Coordinator: the session that closed Wave 96 on 2026-10-08. **Base commit: the commit that
opened Wave 97 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-97-worker-packets.md`).
One card, one worker, one isolated worktree each; merge order C, B, E, D. The card
(`python3 .agents/skills/docket-roadmap/scripts/card_packet.py W97-<X>`) is the contract; this
file is the map. **Read §0 and your own packet only.** Symbols below were located at `924d32cf`
and drift; re-locate every one with `rg -n` before editing.

| Card | Worker | Owning spec bump | Shared-file note |
| --- | --- | --- | --- |
| W97-C | Sonnet | `operator-loop.spec.md` 1.5.3, `pod-dispatch.spec.md` 6.36.3 | regenerates `docs/commands.md` |
| W97-B | Sonnet | `cli-json-shapes.spec.md` 1.27.0, `cli-interface.spec.md` 2.1.2 | recaptures `status_--all.golden` |
| W97-E | Sonnet | `model-profiles.spec.md` 3.3.0 | none |
| W97-D | Opus | `cli-interface.spec.md` 2.1.3 (B holds 2.1.2; the integrator orders the changelog) | none |

## 0. Rules for every worker

- **Isolation.** You are in your own worktree on branch `w97-<x>-<slug>`, based on the claim
  commit (verify with `git merge-base HEAD develop`; if it is older than that commit, stop and
  report). Never touch `~/.docket`: every manual CLI run sets `export W=$(mktemp -d); export
  DOCKET_HOME=$W/.docket` (two statements; **never override `HOME`**). pytest isolates
  `DOCKET_HOME` through the autouse fixture in `tests/conftest.py`. **Never call a real model
  endpoint and never probe a real vendor host**; monkeypatch the edge.
- **Commands.** `env -u VIRTUAL_ENV uv run ...` for everything (the worktree inherits a stale
  `VIRTUAL_ENV`). `grep` is ripgrep here; use `command grep` for literal greps over the diff.
- **Never `git stash`.** Set work aside with a WIP commit if you must.
- **Spec first, test first.** Patch the owning spec (version, last-updated date, changelog
  entry, the requirement text), write the RED test, run it and record the failure reason, then
  implement the smallest change. One-line test docstrings; no card ids or dates in test files.
- **Ownership.** Edit only the files your card names plus the owning spec and its unit tests.
  `CHANGELOG.md`, `specs/README.md`, `TODO.md`, `ROADMAP.md`, `README.md`, `CONTRIBUTING.md`,
  `docs/adr/` are the integrator's; put the CHANGELOG line you would have written in your return.
  An adjacent defect is a locator in "Later follow-ups", not an edit.
- **Comments.** Docstrings at most three lines; no narrative comments. Run
  `env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <touched files>` and
  `env -u VIRTUAL_ENV uv run python scripts/maint/measure_function_spans.py --check`.
- **Goldens.** `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` must pass. Only W97-B
  recaptures a golden (`status_--all`), and explains every changed line in its return.
- **Gates before the return:** `env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv
  run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src`; `env -u VIRTUAL_ENV uv run
  pytest -q -p no:cacheprovider` (the default lanes; the exit code is the evidence, `-q` on top of
  the configured `-q` prints no count line); the goldens; `bash scripts/validate-specs.sh` (one
  known TODO warning in harness-mode.spec.md); `env -u VIRTUAL_ENV uv run python
  scripts/gen_cli_docs.py --check` (C regenerates `docs/commands.md` with the same script, no
  `--check`); `env -u VIRTUAL_ENV uv run python scripts/maint/lint_cli_invocations.py --self-check`.
  `scripts/metrics.py --check` is the integrator's (it fails on a branch that adds tests).
- **Commit** on your branch with `git -c core.hooksPath=/dev/null commit`, subject `Type:
  description` (Fix:/Add:/Docs:), ASCII, **no AI mention and no Co-Authored-By trailer**, a body
  that names the spec version and the RED reason. Before committing: `git diff --cached |
  command grep -nE '/home/|/tmp/claude|@gmail|sk-'` must print nothing (`task-`, `risk-` are
  false matches). Do not merge, do not push, do not touch `develop`.
- **Return** the delta shape from `.agents/skills/docket-roadmap/references/multi-agent-delivery.md`
  "Worker return" (card, commit, outcome, user-visible behaviour, changed paths, spec version,
  oracles, focused tests, full gates, missing, follow-ups, CHANGELOG line). No logs.

## W97-B — `status` knows a parked question and the sandbox

- Live path: `src/docket/cli/_status.py::_pod_status` (counts and `state`; the dict it returns is
  the `--json` object) and the human renderer in the same module (`Isolation:` and `Tasks:`
  lines). Task statuses are strings on `core.dispatch.read_tasks(project)` records;
  `waiting_input` is the parked-question state (`specs/data/cli-json-shapes.spec.md` task
  status enum, `specs/functional/operator-loop.spec.md`).
- Sandbox reader: `src/docket/cli/_setup_sandbox.py::sandbox_state()` (`isolation`,
  `isolationEnabled`, `network`, `backend`; it reads fleet flags and probes binaries, writes
  nothing). Import it from `_status.py` (both are `cli/`), do not duplicate the reader. Phrase
  suggestion: `on (bwrap, network open)` / `off (default); bwrap found, network open` -- pick one
  short form, use the same string in JSON `isolation` and the human line, and state it in both
  specs.
- Specs: `specs/data/cli-json-shapes.spec.md` "### `docket status --json`" (`tasks` keys and the
  `status` enum text); `specs/api/cli-interface.spec.md` `#### docket status` (locate with `rg -n
  "Isolation|waiting approval" specs/api/cli-interface.spec.md`).
- Tests: `tests/unit/cli/test__status.py` (fixtures for a scripted queue are there; see
  `test_json_carries_tasks_usage_last_run_and_the_start_flag` and
  `test_approved_ready_counts_a_granted_pending_task`). RED: a queue with one `waiting_input`
  task gives `tasks.waitingInput == 1` and `status == "waiting"`; the isolation phrase matches
  `sandbox_state()`.
- Golden: `tests/golden/cases/readonly/status_--all.golden` changes deliberately (`bash
  tests/golden/run.sh` has a capture verb; read its header). Explain each changed line.
- Forbidden: `core/`, `cli/_inbox.py`, `cli/_setup_sandbox.py` (read it, do not edit it).

## W97-C — help and messages tell the truth

- Five docstrings: `rg -n "2026-10-08T10-00" src/docket/cli/_task.py` (approve, deny, answer,
  retry, cancel). Replace the operand with `task-04ff`; `answer` keeps `--option opt2`. Then
  regenerate `docs/commands.md` (`env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py`) and
  commit it; `scripts/maint/lint_cli_invocations.py --self-check` and
  `tests/guards/test_cli_invocations_true.py` must stay green.
- Forecast line: `src/docket/cli/_task.py` (`rg -n "May ask you" src/docket/cli/_task.py`);
  kinds are `policy`, `pipeline_gate`, `role_gate` (`core/interruptions.py::ASK_KINDS`).
  Pluralise by count: `1 policy`, `2 policies`, `1 pipeline gate`, `2 pipeline gates`, `1 role
  gate`, `2 role gates`. Keep the ` -- see: docket task show <short id>` tail. Spec:
  `specs/functional/operator-loop.spec.md` (`rg -n "May ask you" specs/functional/operator-loop.spec.md`).
- Policy description: `src/docket/core/interruptions.py::_policy_pattern` and the
  `Interruption(kind="policy", ...)` site. Describe in words: a `match.pattern`/`when.matches`
  policy as `commands matching its pattern`, a structured `when` as the predicate's keys
  (`tool`, `path`, `branch`, `anyOf`...) e.g. `tool bash on path src/**`; never the regex text.
  Keep `detail=policy_id`. `task show` prints `description` (`cli/_task.py`, the interruptions
  block) and the JSON carries `{kind, description, detail}`; no shape change.
- `pod set` message: `src/docket/core/pod.py::PodSettings._validated` is called by `load_for`
  (read path, keep `invalid stored value`) and by `coerce` (set path: `<key>: invalid value
  <v!r> (<rule>)`). A keyword such as `stored: bool` or a message prefix parameter is enough.
  Spec: `specs/functional/pod-dispatch.spec.md` (`rg -n "present-but-invalid|invalid stored"
  specs/functional/pod-dispatch.spec.md`), 6.36.3, a clarification line.
- Tests: `tests/unit/cli/test__task.py` (help text of the five verbs via `CliRunner`; the
  forecast line, see existing tests around `May ask you`), `tests/unit/core/test_pod.py`
  (`coerce` message), `tests/unit/core/test_interruptions.py` (policy description without
  regex metacharacters).
- Forbidden: `cli/_status.py`, `cli/_progress.py`, `cli/_setup_model.py`, the invocation
  linter.

## W97-D — `--progress` names the hop

- Live path: `src/docket/cli/_progress.py::render_event` and `_RENDERABLE_EVENT_TYPES`;
  `dispatch_with_progress` feeds every in-process trace record through it.
- Events: the dispatch session is opened per task in `core/dispatch.py` (`rg -n
  '"session_start"' src/docket/core/dispatch.py`: payload `{"source":"dispatch","task":<id>,
  "resumed":...}`, role `lead`, session id `agent:<project>:<task-id>`) and closed with
  `session_end` `{"status": ...}`. The hop marker is the `tool_call` event written just before
  the hop runs (`rg -n '"hop": role, "agent": member_id' src/docket/core/dispatch.py`), payload
  exactly `{"hop": <role>, "agent": <member id>}`; the agent loop's own `tool_call` events carry
  other keys and must return `None`. Confirm the record's field names (`session_id`, `agent_role`,
  `payload`) in `core/trace.py::trace_event` and in the test helper `_record` of
  `tests/unit/cli/test__progress.py`; if a record has no `session_id`, use the `task` key of the
  `session_start` payload and fall back to the role, and say so in the return.
- Short id: `rg -n "def short_id" src/docket` (use the existing helper; `cli/_task.py` or
  `core/task_ref.py`).
- Spec: `specs/api/cli-interface.spec.md` "## Foreground dispatch progress and in-place
  approval" > "### Rendering": rewrite the four bullets to the decision in the card (task lines,
  the indented hop line, approval lines unchanged, "No other trace event type renders a line"
  now reads "No other trace event renders a line"), version 2.1.3, changelog entry. W97-B adds
  2.1.2 in parallel; put your entry above the current top entry and the integrator orders them.
- Tests: `tests/unit/cli/test__progress.py` `TestRenderEvent` (the three RED cases of the card
  plus the other-`tool_call`-is-None case) and `TestDispatchWithProgress` (emit a hop marker
  between session_start and the approval in `fake_execute`; assert order).
- Goldens must stay byte-identical (no TTY, no `--progress` in any golden case).
- Forbidden: `core/dispatch.py`, `core/trace.py`, `cli/_run.py`, any other spec.

## W97-E — `setup provider add` records the advertised model

- Live path: `src/docket/cli/_setup_model.py::add_provider` -> `_build_spec` (row id defaults to
  `local-model` when no catalog entry and no `--model`) -> `_register` ->
  `core/provider.py::register_provider(spec, *, probe=None)` (probes `/models` through
  `edges/adapters/llm.py::probe_models`, classifies with `verify_endpoint`, saves). The
  verification carries `advertised` (sorted ids the probe returned that are not in `spec.models`).
- Shape: in `_register` (or `add_provider`), when the row was defaulted, probe once
  (`probe_models(endpoint)` built the way `register_provider` builds it, or a small pure helper
  in `core/provider.py` that returns the `ProbeResult` for a spec), rebuild the spec with the
  first advertised id, then `register_provider(spec, probe=probe)`. `advertised` is computed
  against `spec.models`, so after the rebuild the chosen id is no longer "also advertised".
  Success line names the row (`Provider x: <url> (model abc)` or a second line); with no
  advertised id, say `no model advertised; recorded local-model`.
- Spec: `specs/functional/model-profiles.spec.md` (`rg -n "Provider readiness|local-model|
  advertis" specs/functional/model-profiles.spec.md`), 3.3.0, requirement + changelog.
- Tests: `tests/unit/cli/test__setup_model.py` (see how existing `add` tests fake the probe:
  `rg -n "probe_models|ProbeResult" tests/unit/cli/test__setup_model.py tests/unit/core/test_provider.py`).
  Three RED cases from the card. Never a real host.
- Forbidden: `templates/providers/`, `core/models_policy.py`, `cli/_setup.py`.
