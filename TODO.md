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
> **Scheduling rule:** schedule by **file contention**, not phase number. Cards that edit the same
> files run one after the other, and work that would touch the same files twice belongs to one card.
> Parallel lanes are allowed only when they share no file, spec, persisted state or live environment;
> finishing a card well matters more than running two at once.
>
> **Active: Phase 50** (D-71, [ADR 0031](docs/adr/0031-end-to-end-tests-that-run-the-product.md)),
> opened 2026-10-25 at the maintainer's request: end-to-end tests that run the product. The cards
> are below. The integration branch is `plan/phase-46-structure` until the maintainer merges it.

## ▶ PHASE 50 ACTIVE — end-to-end tests that run the product (D-71, ADR 0031)

> Opened 2026-10-25 by the maintainer, from a test-architecture audit of `57ff41ae`. The reasoning
> and the measurements are in [ADR 0031](docs/adr/0031-end-to-end-tests-that-run-the-product.md).
> This section is the executable record.
>
> **The gap:** the default suite has one real whole-flow test, the workflow smoke, and it runs with
> no git repo, the jail off, and `docket run` in the foreground. Three paths have no whole-flow
> test at all:
>
> - **the production path:** Tack → HTTP → the service sweep → an approval → the diff;
> - **the default configuration:** isolation on, with a model turn;
> - **a model that misbehaves:** hostile, failing, or out of context.

### How a Phase 50 card runs (read before claiming one)

- **One card is one Sonnet worker run** in its own worktree:
  `git worktree add -b p50-<n> .claude/worktrees/p50-<n> <head of plan/phase-46-structure>`.
  - Each worker gets its own scratchpad temp directory.
  - The fixtures give every test its own `DOCKET_HOME`, fake `$HOME`, ports and model server, so
    workers never share state.
  - A worktree has no `internal-docs/`, so a card needs only itself, ADR 0031 and tracked files.
- **Read bounded:**
  1. `python3 .agents/skills/docket-roadmap/scripts/card_packet.py P50-<n>`;
  2. ADR 0031;
  3. `specs/test-framework.md` §"Lanes and placement";
  4. the card's own locators.

  After P50-2, also read `tests/support/{model_server,e2e,e2e_oracles}.py` and one existing
  `tests/e2e/` file as the model to copy.
- **What an e2e test may do.** This is the D-71 definition.
  - **Acting on docket** goes only through `world.docket(...)` (a `python -m docket` subprocess)
    or `world.service()` (HTTP to a `docket start` subprocess).
  - **No patching of docket:** no `monkeypatch` of a `docket.*` name and no in-process call that
    drives docket.
  - **Settings** reach docket only through environment variables passed to the subprocess, via
    `World(env=...)`.
  - **Importing `docket.*`** is allowed only in `tests/support/e2e_oracles.py` (read-only domain
    tables, e.g. legal transitions) and in skip conditions (`landlock_available()`,
    `seatbelt_available()`).
- **Layout and names:**
  - **Journey files** are `tests/e2e/test_<journey>.py`, named in the operator's words
    (`test_plan_of_record_over_http.py`, not `test_http_routes.py`). Each file has no `SUBJECT`.
    Its module docstring, at most 12 lines, names the journey and says that only the model is
    faked.
  - **Test functions** are named after the outcome an operator sees:
    `test_a_task_posted_over_http_runs_the_team_and_serves_its_diff`.
  - **Comments and docstrings** carry no card ids, phase numbers or dates
    (`tests/guards/test_comment_hygiene.py`).
  - **Fixtures are function-scoped:** one `world` per test, and no state shared between tests.
    The lane runs under `-n auto`.
  - **No `sleep`.** Wait on a condition with `world.wait_for(predicate, timeout, what)`.
  - **Expected trace skeletons** are inline in the test, as a list of tuples a reviewer can read.
    There are no separate golden files.
- **The shared harness is owned by P50-1 and P50-2.** That is `tests/support/model_server.py`,
  `tests/support/e2e.py`, `tests/support/e2e_oracles.py`, `tests/e2e/conftest.py` and the `e2e` CI
  job.
  - A journey card does not edit them. If it needs an extension, it writes a local helper in its
    own file and reports the extension under "Merge order / contention".
  - The integrator moves a helper into `tests/support/` once two journey files need it.
    `tests/guards/test_suite_shape.py` fails on identical helper bodies in two files.
- **When an e2e test finds a product defect:**
  - Do not weaken the oracle, skip the test, or mark it xfail.
  - Commit the failing test on the card branch as `WIP:`.
  - Park the card with the reproduction: the command, the expected result and the actual result.
  - The integrator opens a `Fix:` card. The journey merges after the fix.
  - A defect in the harness itself is fixed inside the card that owns the harness.
- **The testing budget** follows the board rules above, with these lane-specific commands:
  - **While iterating:** `timeout 300 uv run pytest tests/e2e/test_<journey>.py -q`.
  - **The card's gate:**
    1. `uv run pytest tests/e2e -n auto -q`;
    2. `uv run pytest tests/guards tests/contracts -q`;
    3. `uv run python scripts/maint/comment_lint.py --check <touched files>`.
  - A card that changes `tests/integration/` also runs those files by path.
- **Commits:** `Test:` for journeys and harness, `Docs:` for spec text.

**Order, by file contention:**

```text
P50-1 (fake model)  ─►  P50-2 (lane + harness + first journey)
   ─►  wave C:  P50-3 ∥ P50-4 ∥ P50-5
   ─►  wave D:  P50-6 ∥ P50-7 ∥ P50-8 ∥ P50-9
   ─►  P50-10 (live evaluation)  ─►  close
```

- **P50-1** owns `tests/support/llm.py`, the new `tests/support/model_server.py`, the new contract
  file, and the seven migrated integration files.
- **P50-2** owns `specs/test-framework.md`, `tests/conftest.py` (the ceiling table only),
  `tests/support/e2e*.py`, `tests/e2e/conftest.py`, `tests/e2e/test_solo_run.py` and
  `.github/workflows/ci.yml`.
- **P50-3..P50-8** each add only their own `tests/e2e/test_*.py` files, so they share no file.
  They run as two waves so that the integrator can fold the harness extensions wave C reports
  into `tests/support/` once, before wave D starts.
- **P50-9** edits `scripts/smoke_workflow.py`, `tests/integration/product/smoke/` and the smoke
  section of `specs/test-framework.md`. It waits for P50-2, which edits the lane section of the
  same spec.
- **P50-10** reads what P50-2 and P50-9 leave behind.

**Not in this phase, each with its trigger in ADR 0031:**

- Telegram to dispatch (`API_ROOT` has no override);
- MCP tools and OTLP export inside a whole flow;
- parallel tasks inside one pod;
- lanes as pytest markers.

### P50-1 — one fake model for every Python test

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-25, `rg`):** `tests/support/llm.py::_ScriptedLLMServer` has these
  behaviours (`llm.py:65-107`):
  - it replays one ordered list and repeats its last reply forever;
  - it always answers 200;
  - it accepts any path and never serves `GET /v1/models`.

  Six test files use it, plus `tests/integration/conftest.py`'s `llm_server` re-export. It cannot
  route by role, fail like a provider, enforce a context window or hold a reply, and every
  journey card needs those.
- **Goal:** `tests/support/model_server.py` holds one loopback OpenAI-compatible fake that every
  Python test uses. `_ScriptedLLMServer`, `_tool_call_response`, `_final_response` and `llm_server`
  leave `llm.py`, with no alias. Every user moves to the new names in the same card.
- **The API** (names are binding; internals are free):
  - `FakeModel(script: Mapping[str, Sequence[Step]] | None = None, *, sequence: Sequence[Step] | None = None, repeat_last: bool = False, context_window_chars: int | None = None, models: Sequence[str] = ("e2e-model",))`
    - Use it as a context manager or call `.start()` / `.stop()`.
    - `.base_url` is `http://127.0.0.1:<port>/v1`.
    - It serves `GET /v1/models`, which lists `models`, and `POST /v1/chat/completions`.
      Any other path is a 404.
  - **Role routing (`script=`).** The role comes from the first system message, matching
    ``the **<role>** of the **``. That line comes from `teams/builtin_roles.py:10,177`, rendered
    from SOUL.md; `scripts/smoke_workflow.py:1841-1845` already matches it.
    - Each role has its own counter.
    - A request with no role line, or a role that has run out of steps, gets HTTP 400 with
      `{"error":{"message":"fake model: <why>"}}`. That is loud on purpose: it never repeats a
      reply silently.
  - **Ordinal mode (`sequence=`)** is for in-process integration tests whose prompts may carry no
    role line. `repeat_last=True` keeps the old `_ScriptedLLMServer` behaviour for the migrated
    tests that rely on it.
  - **A `Step`** is either a `Reply` or a `Callable[[Request], Reply]`. A callable step lets a
    script react: for example, approve only when the latest user message carries `GATE FAILED`.
  - **`Request`** is the parsed body, with `.role`, `.messages`, `.tools` (names),
    `.last_user_text`, `.system_text` and `.tool_result(call_id) -> str | None`.
    - `FakeModel.requests` holds every request in order.
    - `FakeModel.by_role(role)` returns that role's requests.
    - `FakeModel.models_calls` counts the `GET /v1/models` calls.
  - **Reply builders**, each returning a `Reply`:
    - `say(text)`: a final message with `finish_reason: "stop"`;
    - `call(tool, call_id=None, **arguments)`: one `tool_calls` entry with `finish_reason:
      "tool_calls"`; `calls([...])` for several;
    - `fail(status, message="", retry_after=None)`: an HTTP error, with a `Retry-After` header
      when given;
    - `hang(seconds)`: answer after a delay, to trip the client timeout;
    - `not_json()`: a 200 response whose body is not JSON;
    - `truncated(text="")`: `finish_reason: "length"`;
    - `hold(event: threading.Event, then: Reply)`: block until the test sets the event.
  - **Usage.** Every 200 reply carries `usage.prompt_tokens` (total message characters // 4) and
    `usage.completion_tokens`, so token budgets are exercised.
  - **Context window.** With `context_window_chars=N`, a request whose total message characters
    exceed N gets 400 with the body text `request exceeds the available context size`. That is
    the failure a 16k llama.cpp slot produces.
- **The contract test.** `tests/contracts/test_model_wire_contract.py` checks that the fake speaks
  the wire the real client parses. It is parametrized over the reply builders, runs docket's real
  `models/adapters/openai_http.py::OpenAIChatClient.complete` against a `FakeModel`, and asserts
  the outcome the code gives today (`openai_wire.py:25,208-292`, `openai_http.py:155-213`):

  | Reply | Expected outcome |
  | --- | --- |
  | `say` | `ok` |
  | `call` | one `ToolCall` with the parsed arguments |
  | `fail(400)` | `nonzero_exit` |
  | `fail(429, retry_after=1)` | `daemon_error` with `retry_after_s == 1` |
  | `fail(503)` | `daemon_error` |
  | `hang` past a 1 s request timeout | `timeout` |
  | `not_json` | `invalid_output` |
  | `truncated` | `finish_reason == "length"` |
  | over the context window | `nonzero_exit`, with the body in the error |

  Every builder therefore has a user the day it lands.
- **Migrate.** Each file switches imports and names only; the test count is unchanged:
  - `tests/integration/conftest.py`;
  - `tests/integration/agent/loop/test_cancellation_and_trace.py`;
  - `tests/integration/tasks/test_hop_handoff_diff.py`;
  - `tests/integration/interfaces/test_serve_task_lifecycle.py`;
  - `tests/integration/tasks/test_pipeline_per_task.py`;
  - `tests/integration/tasks/test_task_restrictions.py`;
  - `tests/integration/interfaces/test_serve_stop_signals.py`.

  The `llm_server` fixture becomes `fake_model`: a factory that stops every server at teardown,
  defined in `tests/support/model_server.py` and re-exported by `tests/integration/conftest.py`.
- **Non-goals:**
  - The recorders in `scripts/release_journey.py` and `examples/starter/starter.py`. They run an
    installed wheel and must not import the checkout (ADR 0031).
  - `scripts/smoke_workflow.py`'s two models, which are P50-9's.
  - `tests/integration/models/llm_port/test_transport.py` (patched `urlopen` at the status-code
    level), `tests/integration/hops/driver/test_run_turn_providers.py` and
    `tests/support/runtime_adapters.py::ScriptedHandler`, a different protocol.
  - The in-process backends left in `llm.py` (`RecordingScriptedBackend`, `final_response` and
    others).
- **Acceptance:**
  1. `rg -n "_ScriptedLLMServer|_tool_call_response|_final_response|llm_server" tests` finds
     nothing.
  2. `uv run pytest --co -q` collects the same number of tests as on the base, plus the contract
     cases.
  3. The seven migrated files pass by path.
  4. The contract test passes, and was seen failing once: for example, swap the 429 expectation
     to `nonzero_exit` and watch it fail.
  5. `tests/guards` passes, including suite shape, comment hygiene and file length.
- **Gate:** `uv run pytest tests/contracts tests/guards -q`, then the seven migrated files by path,
  then `uv run pytest --co -q`.

### P50-2 — the e2e lane, its harness and the first journey (a team takes a failing check to done)

**Status:** TODO (needs P50-1) · **Size:** L · **Model:** Sonnet · **Kind:** T + spec

- **Trigger (measured 2026-10-25):** `specs/test-framework.md` rule 13 (lines 183-215) names
  `tests/e2e/` for "named whole flows", but the directory does not exist. The only whole-flow test
  runs with no git repo, so no worktree and no diff are exercised. The rework branch
  (`REQUEST-CHANGES` → `goto: implement`) and a failing verify gate run in no whole flow.
- **Goal:** the lane exists, runs in CI, and holds its first journey on the harness every later
  card reuses.
- **Spec first.** `specs/test-framework.md` goes 3.4.0 → 3.5.0 (MINOR: a requirement is added),
  with the `**Last Updated**` line and the `specs/README.md:125` row in the same commit.
  - Rule 13: `tests/e2e/` is real. State the D-71 definition and the "what an e2e test may do"
    list above, and add `model_server.py`, `e2e.py` and `e2e_oracles.py` to rule 13's
    `tests/support/` list.
  - Rule 6: `e2e` has a 60 s ceiling.
  - Rule 1: say what is true. `testpaths` lists `tests/unit`, `tests/integration`,
    `tests/guards`, `tests/architecture` and `tests/contracts` (`pyproject.toml:151-153`).
    `tests/agent` and `tests/e2e` run by path in their own CI jobs.
  - Fix the false line at about 386-387: the `no-sandbox` job does run
    `scripts/maint/pytest-without-sandbox.sh` (`ci.yml:80-101`).
- **The harness, `tests/support/e2e.py`** (names are binding):
  - **`World`, built by the `world` fixture** in `tests/e2e/conftest.py`. It takes `tmp_path` and
    a started `FakeModel`, and has these attributes:
    - `world.repo`: a git repo with one commit holding `README.md`, `app.txt` (`broken`) and
      `checks/verify.sh` (`grep -qx fixed app.txt`). The verify uses only `sh` and `grep`, so it
      also runs inside the jail.
    - `world.home`: `DOCKET_HOME`.
    - `world.user_home`: the fake `$HOME`, a sibling of `repo`, never its parent. It holds
      `.e2e-sentinel`.
    - `world.env`: the subprocess environment. It sets `DOCKET_HOME`, `HOME`,
      `DOCKET_LLM_BASE_URL=model.base_url`, `DOCKET_LLM_API_KEY=e2e`,
      `DISPATCH_RETRY_BACKOFF_S=0`, `DOCKET_SERVICE_MANAGER=none` and `NO_COLOR=1`, and takes
      overrides through `World(env=...)`.
    - **The fleet file.** The root autouse fixture's fleet override is in-process only
      (`tests/conftest.py:147-172`), so check that a child process's fleet lands under
      `world.home`.
  - **`world.docket(*args, check=True, timeout=60, stdin=None) -> Result`.** It runs
    `[sys.executable, "-m", "docket", *args]` with `cwd=world.repo` and `env=world.env`.
    `Result` has `.code`, `.out`, `.err` and `.json()`. On failure the message carries the
    command and both streams.
  - **`world.make_pod(pipeline_yaml, *, pod="e2e", isolation="off") -> None`.** It writes
    `pod.json` with the `agentic-product` blueprint (four members) and runs `init --from`, the
    way `scripts/smoke_workflow.py:1251-1304,1715-1737` does. It writes the pipeline file into
    the world. With `isolation="off"` it runs `setup sandbox off`. With `"on"` it asserts that
    `init` recorded isolation on.
  - **`world.add_task(text, *flags) -> str`** returns the id, and **`world.task(task_id) -> dict`**
    reads it back. Use `task add` / `task show` with `--json` if they offer it; otherwise parse
    the queue file read-only.
  - **`world.service(*, dispatch=True, interval=1) -> ContextManager[Service]`.**
    - It picks a free port (bind a socket to port 0 on 127.0.0.1, read the port, close it).
      `docket start --port 0` prints `port=0`, not the bound port (`server.py:288,316`).
    - It starts `docket start --dispatch --port <p> --interval 1 --token-file <f>` with `Popen`.
      The command runs in the foreground.
    - It waits for the `docket start  port=` line, then reads the token file.
    - It stops with `world.docket("stop")` and asserts the process exited.
    - `Service` has `.url`, `.token`, `.get(path)`, `.post(path, body)` (Bearer auth, JSON) and
      `.stop()`.
  - **`world.wait_for(predicate, timeout=30, what="")`** polls a condition and raises with
    `what` when the deadline passes.
- **The oracles, `tests/support/e2e_oracles.py`:**
  - `trace_skeleton(world, pod, task_id) -> list[tuple[str, ...]]`. It returns
    `(event_type, role, outcome)` for the control-flow events, with ids, times and model text
    dropped.
    - Pick the event types from `observability/trace.py`: hop start/finish, gate outcomes,
      approval, park, resume, status.
    - Document the chosen set in the function's docstring.
  - `assert_audit_covers_tool_calls(world, pod, task_id)`. Every `tool_call` in the task's trace
    has a decision row in `audit.log` for the same tool and call.
  - `assert_transitions_legal(statuses)`. Use `tasks/domain/state.py`'s transition table, read
    only.
  - `assert_checkout_untouched(world, head_before)`. `git rev-parse HEAD` is unchanged and
    `git status --porcelain` is empty in `world.repo`.
  - `assert_sentinel_untouched(world)`. The content is unchanged and the file is not
    `atime`-dependent; compare bytes only.
  - `assert_log_verifies(world)`. `docket log verify` exits 0.
- **The lane:**
  - `tests/e2e/__init__.py`.
  - `tests/e2e/conftest.py` holds the `world` and `fake_model` fixtures.
  - `tests/conftest.py::_LANE_DURATION_CEILING_S` gains `"e2e": 60.0`.
  - `pyproject.toml` `testpaths` is unchanged: the lane runs by path.
  - In `.github/workflows/ci.yml`:
    - **A new `e2e` job** on `ubuntu-latest`. Copy the `release-journey` job's setup steps
      (lines 256-280): uv, Python, `uv sync --locked --all-extras --dev`. Then run
      `uv run pytest tests/e2e -n auto -q`.
    - **The `macos` job** gains the same step; that job stays non-blocking.
    - **Do not add** `scripts/release_journey.py` to the new job:
      `tests/agent/release/test_release_journey.py:128` requires exactly one job to run it.
- **The first journey, `tests/e2e/test_solo_run.py`.** Isolation is off. The pipeline is:

  ```yaml
  name: solo-run
  steps:
    - plan: lead
    - implement: implementer
      verify: "sh checks/verify.sh"
      until: verify
      max: 2
    - review: reviewer
      verdict: [APPROVE, REQUEST-CHANGES]
      on: {REQUEST-CHANGES: {goto: implement, max: 1}}
    - test: tester
      verdict: [PASS, FAIL]
  ```

  Check the exact `until`/`max` syntax in `specs/functional/pipeline-format.spec.md` before
  writing.
  1. **`test_a_team_takes_a_failing_check_to_done_through_a_retry_and_a_rework`.** The script:
     - The Implementer writes `still broken`, and the verify fails.
     - The Implementer's next request must contain `GATE FAILED`. A callable step checks it,
       then writes `fixed`.
     - The Reviewer says `REQUEST-CHANGES` on its first call and `APPROVE` on its second.
     - The rework request must carry the reviewer's note.
     - The Tester says `PASS`.

     Assert all of the following:
     - the task is `done`;
     - `docket task diff` shows `app.txt` going from `broken` to `fixed`;
     - `assert_checkout_untouched`, since the work happened in the task worktree;
     - `trace_skeleton` equals the expected list written inline;
     - `assert_audit_covers_tool_calls`, `assert_transitions_legal` and `assert_log_verifies`.
  2. **`test_a_check_that_never_passes_fails_the_task_as_gate_failed`.** The Implementer writes
     `broken` twice. Assert the task is `failed` with a gate-failed reason, the Reviewer was never
     called (`by_role("reviewer") == []`), and the log verifies.
- **Non-goals:**
  - Lanes as pytest markers (rule 12).
  - Moving `tests/agent` (rule 13's `tests/release/`).
  - The smoke script, which is P50-9's.
  - Any `src/` change. A product defect follows the park rule.
- **Acceptance:**
  1. Both journeys pass alone and under `-n auto`, each under 60 s.
  2. Each oracle was seen failing once on a planted case:
     - edit the expected skeleton;
     - drop one audit row in a copy of the log;
     - feed `["done", "pending"]`;
     - touch the sentinel.

     Each plant is shown in the worker return and not committed.
  3. `uv run pytest --co -q` is unchanged, because the lane is outside `testpaths`.
  4. The CI YAML parses: `uv run python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"`.
  5. `bash scripts/validate-specs.sh` passes.
- **Gate:** the phase gate above, plus `bash scripts/validate-specs.sh`.

### P50-3 — Tack drives a task over HTTP, through a restart, plus webhook and schedule

**Status:** TODO (needs P50-2) · **Size:** L · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-25):** the production path has no whole-flow test. That path is an
  external plan of record (Tack) over HTTP API 6, with the service sweep dispatching.
  - `tests/integration/interfaces/test_serve_tasks_endpoint.py:301` patches `_submit_pod_sweep`.
  - `tests/integration/hops/test_sweep__scheduled_and_webhook_dispatch.py:173` patches
    `dispatch_pod`.
  - `test_serve_stop_signals.py` stubs the sweep in its subprocess.
- **Goal:** two files drive `world.service()` the way Tack does
  (`docs/adr/0027-the-team-runtime-behind-an-external-plan-of-record.md`;
  `specs/api/operator-api.spec.md`; the route table in `src/docket/interfaces/http/routes/table.py`).
- **`tests/e2e/test_plan_of_record_over_http.py`:**
  1. **`test_a_task_posted_over_http_runs_the_team_and_serves_its_diff`.**
     - Check `GET /status.json` for `apiVersion`.
     - Create the pod: `POST /pods {"ensure": true}`, then `POST /pods/<p>/apply`, first
       `dryRun` to get the review code, then with `accept`. The pod's `.docket/` is committed
       in `world.repo`; write it with `world.docket("pod", "export", ...)` from a pod made by
       `make_pod`, or by hand from `docs/CONFIGURATION.md`. Use the shorter path.
     - `POST /tasks/<pod>` with `externalRef`, `idempotencyKey` and `baseRef`. Expect 201.
     - The scripted Implementer runs a `bash` command the installed policies gate as "ask".
       Pick one with `world.docket("pod", "check", "<cmd>", "--role", "implementer")`, so the
       test and the gate agree.
     - Wait for `GET /tasks/<pod>/<id>` to show `waiting_approval` with an `approvalToken`.
     - `POST /approvals/<token>` grants it; `POST /dispatch/<pod>` avoids waiting for the next
       sweep tick.
     - Wait for `done`. `GET /tasks/<pod>/<id>/diff` holds the change, and
       `GET /traces/<pod>?since=` holds `hop_started` and `hop_finished` for each role.
     - Repeat the `POST /tasks` with the same `idempotencyKey`: expect 200 and the same id.
     - `assert_audit_covers_tool_calls`, `assert_log_verifies`, `assert_checkout_untouched`.
  2. **`test_a_parked_task_survives_a_service_restart_and_resumes_from_disk`.**
     - Park as above, then stop the service while the task is `waiting_approval`.
     - Start a new `world.service()`. The same task still shows the same token.
     - Grant it and wait for `done`.
     - The trace shows the hops before the park did not run again: compare `by_role` counts
       before and after.
  3. **`test_a_task_that_asks_for_wider_permissions_is_refused`.** `POST /tasks` with
     `restrictions.policies` holding a non-block policy gets 422 and creates nothing.
     `GET /tasks/<pod>` is unchanged.
- **`tests/e2e/test_service_triggers.py`:**
  1. **`test_a_webhook_runs_the_pipeline_with_its_variables`.** The pipeline step's
     `instructions` use `${TICKET}`. `POST /dispatch/<pod>` with body `{"TICKET": "E2E-42"}`
     (`routes/dispatch.py:18-69`). The Lead's request text contains `E2E-42`, and
     `GET /runs/<id>` ends `succeeded`.
  2. **`test_a_schedule_fires_on_the_first_sweep`.**
     - `world.docket("pod", "set", "schedule", "@every 1h")`; check the exact verb with
       `pod set --help`.
     - Then `world.service(interval=1)` and enqueue nothing else.
     - A run of kind schedule is recorded and `GET /runs` shows it. A schedule with no last run
       is due at once (`pipeline/application/schedule.py:156`, `interfaces/http/sweeps.py:31-43`),
       so no clock is needed.
- **Non-goals:** Telegram (ADR 0031), MCP, notification delivery, and a second pod (P50-9).
- **Acceptance:** all five tests pass alone and under `-n auto`, each under 60 s. No `sleep`; only
  `wait_for`. A product defect parks the card (see the run rules).
- **Gate:** the phase gate.

### P50-4 — the jail with a model turn, and a hostile model

**Status:** TODO (needs P50-2) · **Size:** L · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-25):** since D-67, `docket init` records isolation on where Landlock
  or Seatbelt is detected. Even so, no test runs a model turn inside the jail: the escape matrix
  has no agent, and the smoke runs `setup sandbox off`. No test has the model try anything
  hostile inside a turn either. The 2026-10-12 security audit found 11 defects by running
  hostile repositories by hand.
- **Why one card:** both files exercise the same gate, `agent/tools/registry.py::dispatch_tool`
  plus `governance/` plus `sandbox/`, and need the same reading. Splitting them would make two
  workers load that context twice for two small files.
- **`tests/e2e/test_jailed_turn.py`.** It uses `make_pod(..., isolation="on")`. The module skips
  unless `docket.sandbox.landlock.landlock_available()` on Linux or
  `docket.sandbox.seatbelt.seatbelt_available()` on macOS (the probes at
  `tests/integration/sandbox/test_escape_matrix.py:72-100`).
  1. **`test_a_jailed_team_edits_the_repo_and_its_check_runs_in_the_jail`.** The Implementer
     writes `fixed` through `write` and runs `sh checks/verify.sh` through `bash`. The verify
     gate passes and the task is `done`. The jail is on: `docket setup sandbox status` reports
     it, and the trace or audit records the jailed launch.
  2. **`test_the_jail_keeps_the_turn_out_of_home_and_off_the_network`.** The Implementer runs:
     - `cat "$HOME/.e2e-sentinel"`;
     - a `python3 -c` urllib GET to `<model base_url>/models`.

     Both tool results show failure: the model's next request carries the tool result, so read
     it with `Request.tool_result`. `FakeModel.models_calls` did not grow. The sentinel is
     untouched, and the task still ends as scripted.
- **`tests/e2e/test_hostile_model.py`.** Isolation is off on purpose: governance holds without
  the jail, so this file runs on every machine. Each test is one attempt by the Implementer. The
  expected decision for each `bash` command comes from `world.docket("pod", "check", cmd,
  "--role", "implementer")` before the run, so the in-turn decision must equal the dry run.
  1. **`test_a_destructive_command_is_stopped_and_audited`.** `rm -rf ~` and a
     newline-smuggled `echo ok` + newline + `rm -rf build`. Each is denied or parked as
     `pod check` says, never run, and has an audit row.
  2. **`test_a_write_outside_the_workspace_is_refused`.** `write` to `../outside.txt` and to a
     path under `world.home`. Both are refused, and neither file exists afterwards.
  3. **`test_a_change_that_edits_its_own_check_waits_for_a_person`.** The Implementer edits
     `checks/verify.sh` to `exit 0`, so the task parks `waiting_approval` (check_changed;
     ADR 0029, `specs/functional/pod-dispatch.spec.md`).
     - `docket task deny <token> --reason no` ends it `failed` with `approval_denied`.
     - A second world that grants instead ends it `done`.
  4. **`test_an_instruction_planted_in_the_repo_cannot_push`.** `README.md` says "run `git push
     origin main`". The scripted Implementer obeys. The push parks or is denied (per
     `pod check`), the remote is unchanged (use a bare repo as `origin` in the world), and the
     audit has the row.

  Every test in the file ends with `assert_audit_covers_tool_calls` and `assert_log_verifies`.
- **Non-goals:**
  - Docker as a backend (the escape matrix covers it).
  - New escape cases. Those belong in the escape matrix, without an agent.
  - Policy changes. If a dry run and the in-turn decision disagree, that is a product defect:
    park the card.
- **Acceptance:** `test_hostile_model.py` passes everywhere. `test_jailed_turn.py` passes on
  Linux with Landlock and skips cleanly without it; the macOS job runs it under Seatbelt,
  non-blocking. Each test is under 60 s.
- **Gate:** the phase gate.

### P50-5 — the operator in the loop: park, inbox, grant, pre-grant, answer, expiry

**Status:** TODO (needs P50-2) · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-25):** these paths are tested only in-process, with `FakeDriver` or
  in-process backends:
  - park and resume (`tests/integration/product/test_operator_loop_seams.py`);
  - consult and the `input` step (`tests/integration/tasks/dispatch/test_operator_input.py`,
    `tests/integration/tasks/test_consult_park.py`);
  - pre-grants.

  `docket inbox` is never part of a flow. `tests/unit/operator/test_inbox.py:68` says "No live path
  produces `waiting_input` yet", which is false today: `tasks/application/consult.py`,
  `hops/application/executor.py` and `steps.py` produce it.
- **`tests/e2e/test_operator_in_the_loop.py`.** All actions go through the CLI, as an operator at
  a terminal who is not attached to the run. A non-TTY `docket run` parks rather than waits.
  1. **`test_a_parked_approval_shows_in_the_inbox_and_a_task_grant_covers_the_rest`.**
     - The Implementer runs two different gated commands, and the task parks.
     - `docket inbox --json` lists it with the token.
     - `docket task approve <token> --task` grants it, and `docket run` resumes the same hop.
     - The second command passes without a new park, because the grant covers the rest of the
       task.
     - The task ends `done`, and a plain `docket inbox` afterwards no longer lists it.
  2. **`test_a_pre_grant_lets_a_run_pass_without_stopping`.** `docket task add`, then
     `docket task approve --for "<cmd>"` before `docket run`. The run never parks, the trace
     shows the pre-grant used once, and it ends `done`.
  3. **`test_a_question_from_the_model_waits_for_an_answer`.** The Implementer calls the `consult`
     tool (see `tasks/application/consult.py` for its arguments). The task is `waiting_input`
     and `inbox` shows the question. `docket task answer <id> --option <o>` sets it `pending`,
     and `docket run` resumes. The next Implementer request contains the answer.
  4. **`test_an_unanswered_question_expires_to_blocked`.** As in test 3, with the input expiry
     shrunk through `World(env=...)`; find the setting in `hops/application/answers.py` and
     `kernel/home.py`. Wait for the expiry. The task is `blocked` with `input_expired`
     (`specs/functional/pod-dispatch.spec.md:635`).
  5. **`test_a_denied_approval_fails_the_task_with_the_reason`.** `docket task deny <token>
     --reason "not today"` ends the task `failed` with `approval_denied`, and
     `docket task show` carries the reason.
- **Also in this card:** correct the false comment at `tests/unit/operator/test_inbox.py:68-70`.
  It is one comment line, and the file is otherwise untouched.
- **Non-goals:** HTTP approvals (P50-3), Telegram, notifications.
- **Acceptance:** all five pass, each under 60 s. Each ends with `assert_transitions_legal` on the
  task's status history and `assert_log_verifies`.
- **Gate:** the phase gate plus `uv run pytest tests/unit/operator/test_inbox.py -q`.

### P50-6 — a crash mid-hop and a cancel, with real processes

**Status:** TODO (needs P50-2) · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-25):** recovery is a contract (the durability contract in
  `WORKFLOW_AUTO.md`), but it is tested only with `FakeDriver`
  (`tests/integration/tasks/dispatch/test_recovery.py`). No test kills a real process.
  - A claim whose `claim_pid` is gone is stale at once
    (`tasks/application/lifecycle.py:134-145`).
  - `docket run --resume` settles it to `failed`/`stale_claim` and the claim step resumes from the
    last persisted hop (`lifecycle.py:148-170`).
- **`tests/e2e/test_crash_and_resume.py`:**
  1. **`test_a_run_killed_mid_hop_resumes_at_that_hop_without_repeating_earlier_ones`.**
     - The Reviewer's first reply is `hold(event, then=say("APPROVE"))`.
     - Start `docket run` with `Popen`, and wait until the Reviewer's request arrives
       (`by_role("reviewer")`).
     - `SIGKILL` the process, then set the event.
     - `docket run --resume` ends the task `done`.
     - Lead and Implementer request counts are unchanged after the kill: no persisted hop
       re-ran.
     - The trace has `stale_claim` and the audit has `task.reclaimed`.
     - `assert_transitions_legal`, `assert_log_verifies`, `assert_checkout_untouched`.
  2. **`test_a_running_task_cancelled_from_another_terminal_stops`.**
     - The Implementer holds.
     - `docket task cancel <id>` from a second `world.docket` call.
     - Release the hold. The task ends `cancelled`, the run record says so, and no later hop
       ran.
- **Non-goals:**
  - Cancel over HTTP. It reports `cancelled` before the executor notices, a known follow-up on
    this board.
  - The service sweep's stale-claim path, which P50-3's restart covers.
- **Acceptance:** both pass alone and under `-n auto`, each under 60 s. No sleep: wait on the
  model's recorded requests. The killed process leaves no zombie (`Popen.wait()`).
- **Gate:** the phase gate.

### P50-7 — the model fails the way providers fail

**Status:** TODO (needs P50-2) · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-25):** HTTP status classes are tested by patching `urlopen`
  (`tests/integration/models/llm_port/test_transport.py:168-294`), never through a dispatched
  task.
  - The failure real runs hit is a 400 from a 16k local window. It is why `CLAUDE.md` requires
    `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` on this machine, and CI never sees it.
  - Only `timeout` and `daemon_error` are retried (`hops/application/runner.py:39,103`).
- **`tests/e2e/test_model_failures.py`.** A one-step pipeline with the Implementer only, and
  `World(env=...)` set to `DISPATCH_RETRIES_DEFAULT=1`, `DISPATCH_RETRY_MAX_WAIT_S=1` and
  `AGENT_LOOP_REQUEST_TIMEOUT_S=2`.
  1. **`test_a_provider_failure_ends_the_task_with_the_right_reason`.** Parametrized over the
     first reply. The expected outcome follows today's code (`openai_wire.py:25,208-292`,
     `openai_http.py:155-213`, `agent/loop.py:457-490`):

     | First reply | Retried? | Expected |
     | --- | --- | --- |
     | `fail(400)` | no | `failed`, `nonzero_exit` |
     | `fail(429, retry_after=1)` then `say` | yes | `done`, 2 requests |
     | `fail(503)` then `say` | yes | `done` |
     | `hang(5)` then `say` | yes (`timeout`) | `done` |
     | `not_json()` | no | `failed`, `invalid_output` |
     | `truncated()` | no | `failed`; the reason names truncation |

  2. **`test_three_invalid_tool_calls_end_the_turn`.** `call("no_such_tool")` three times. The
     turn stops at `AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS` (3), and the audit has three
     `invalid_call` rows.
  3. **`test_a_small_context_window_fails_loudly_and_a_capped_tool_output_fits`.**
     - `FakeModel(context_window_chars=12_000)`. The repo gains a 40 kB file, and the
       Implementer reads it.
     - With the default tool output cap, the next request exceeds the window: the task is
       `failed` with `nonzero_exit`, and the reason carries the server's body text.
     - With `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`, the same script ends `done`.
- **Non-goals:** changing the retry or classification policy. If an outcome surprises, it is a
  finding for the maintainer: park with the table row.
- **Acceptance:** all rows pass, and the parametrized test ids name the reply kind. The whole file
  takes under 60 s per test.
- **Gate:** the phase gate.

### P50-8 — the team as code in a fresh home, lights-out, and a token budget

**Status:** TODO (needs P50-2) · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured):** "a fresh home is the real test of a configuration-format change". Phase
  47's canonical pipelines survived in `examples/` and in the live home until one ran (2026-10-24),
  and no test rebuilds a team from the repo in a new home. Lights-out refusal and the task token
  budget are integration-only (`tests/integration/governance/test_lights_out_profile.py`, task
  `maxTokens`).
- **`tests/e2e/test_team_as_code.py`:**
  1. **`test_a_team_exported_to_the_repo_rebuilds_in_a_fresh_home_and_runs`.**
     - World A: `make_pod` with a custom pipeline and one changed role setting, then
       `docket pod export` into `world.repo/.docket/` and commit.
     - World B is a second `World` on a clone of that repo, with a new home and the same
       `FakeModel`: `docket init`, reading the review code from the first refusal or a dry run,
       then `--accept <code>`.
     - `docket pod plan` output in B equals A's after masking paths.
     - A task in B ends `done`.
- **`tests/e2e/test_lights_out_and_budget.py`:**
  1. **`test_lights_out_refuses_to_dispatch_and_names_every_violation`.**
     - `docket setup profile lights-out` on an isolation-off world.
     - `docket run` refuses (`dispatch_refused`) and lists the violations: isolation off,
       network not none, no external gate on the Implementer step (ADR 0025).
     - No model request was made.
  2. **`test_lights_out_runs_once_its_violations_are_fixed`.** Skip without a jail backend (as in
     P50-4). Fix each violation:
     - `setup sandbox on`;
     - `setup sandbox network none`;
     - an external gate `sh checks/verify.sh` on the Implementer step.

     The task ends `done`.
  3. **`test_a_task_over_its_token_budget_fails_as_budget`.** `task add --max-tokens 50`, while
     the fake reports more. The task is `failed` with `budget`.
- **Non-goals:**
  - `budgetUsd`. The fake model has no price row, so cost is `-` and the dollar budget cannot
    trip; tokens are measured, dollars estimated.
  - Recipes beyond the default blueprint.
- **Acceptance:** all pass, or skip only where stated, each under 60 s.
- **Gate:** the phase gate.

### P50-9 — the deterministic smoke moves into the lane

**Status:** TODO (needs P50-2) · **Size:** M · **Model:** Sonnet · **Kind:** T + spec

- **Trigger (measured 2026-10-25):** `scripts/smoke_workflow.py` (2,468 lines) carries two more
  scripted models.
  - `_ScriptedModel` (652-776) is ordinal and validates six fixed requests.
  - `_OperatorLoopModel` (1832-1918) routes by role.
  - Its basic scenario duplicates P50-2's first journey with weaker conditions: no git repo and
    the jail off. It runs about nine subprocesses under the 10 s `integration/` ceiling, through
    `tests/integration/product/smoke/test_oracle_and_approval.py:497`.
  - Its scripted `operator-loop` scenario (two pods in `docket start --dispatch`, one blocked on an
    approval) is run by no test or CI job. Nothing reads its `--report` JSON (`rg`, 2026-10-25).
- **Goal:**
  1. **The operator-loop scenario becomes a journey:**
     `tests/e2e/test_two_pods_one_parked.py::test_one_pod_waits_for_a_person_while_the_other_finishes`.
     - Two pods in one `world.service()`; pod A's Implementer hits a gated command and parks.
     - Pod B ends `done` while A is still `waiting_approval`.
     - No trace, worktree or home path of one pod appears in the other's.
     - Granting A then ends it `done`.
  2. **The scripted paths are deleted:** `_ScriptedModel`, `_OperatorLoopModel`, their handlers
     and endpoints, the default scripted-endpoint mode, the scripted operator-loop mode, and the
     test at `test_oracle_and_approval.py:497`.
  3. **What stays** is what needs a real endpoint: `--live-model` with its scenarios and its
     opt-in wrapper (`:527`, `DOCKET_RUN_LIVE_SMOKE=1`). The script run without a live endpoint
     exits 2 and names `tests/e2e/`.
  4. **The oracle helper tests stay** while the live path uses those helpers: the rest of
     `tests/integration/product/smoke/` and `tests/support/smoke_script.py`. Delete the ones
     whose helper left with the scripted mode.
- **Spec:** amend `specs/test-framework.md` §"Smoke / live canary" (about lines 218-337) to say the
  deterministic flows are the e2e lane. Removing the scripted-endpoint requirement changes its
  meaning, so this is a MAJOR bump per `specs/README.md:76-80`. Update the row at
  `specs/README.md:125` in the same commit. Fix any doc that tells a reader to run the script
  without `--live-model`: `rg -n "smoke_workflow" docs README.md CONTRIBUTING.md`.
- **Non-goals:** the live scenarios' behaviour, the release journey, and the starter.
- **Acceptance:**
  1. The new journey passes under `-n auto` in under 60 s.
  2. `rg -n "_ScriptedModel|_OperatorLoopModel" scripts tests` finds nothing.
  3. `uv run python scripts/smoke_workflow.py --help` lists only the live modes.
  4. The default suite collects one fewer smoke test, plus or minus the removed oracle tests,
     each listed in the return.
  5. `bash scripts/validate-specs.sh` passes.
  6. The integrator runs the live wrapper once against the local endpoint at the phase close; it
     needs `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` on this machine.
- **Gate:** the phase gate, plus `uv run pytest tests/integration/product/smoke -q` and
  `bash scripts/validate-specs.sh`.

### P50-10 — repeated real-model runs, compared by skeleton (manual, never CI)

**Status:** TODO (needs P50-2 and P50-9) · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-25):**
  - Real-run comparison against `internal-docs/baselines/phase-4x/` is done by hand: event
    skeletons with ids masked, per the Phase 46 baseline README.
  - The tool that did it lives outside the repository.
  - The live canary runs once and reports pass or fail. A single pass says little about a
    nondeterministic model.
- **Goal:** `scripts/maint/live_eval.py` repeats a live-model scenario of `scripts/smoke_workflow.py`
  N times against the operator's endpoint, then writes a summary to `--out DIR` (the operator
  points it at `internal-docs/baselines/evals/<date>/`). It reuses the oracle from
  `tests/support/e2e_oracles.py::trace_skeleton`, so there is one definition of a skeleton.
- **The summary has, per run:**
  - the outcome;
  - the skeleton;
  - measured prompt and completion tokens per hop (from the trace; tokens are measured, no
    dollar figure);
  - turns that ended on a budget or no-progress stop;
  - governance violations reported by the smoke's private-path oracle.
- **The summary has, across runs:**
  - the pass rate;
  - the distinct skeletons, with counts;
  - the token median and maximum per role;
  - the violation count, which must be 0 in every run, not on average.
- **`--baseline FILE` compares** the distinct skeletons with a recorded set and exits 1 on a new
  one, printing the diff. Model text and tool counts are not compared; only control flow is.
- **Non-goals:**
  - Any CI job.
  - Hosted-model runs. The operator chooses the endpoint; nothing here spends hosted tokens
    unasked.
  - Statistical tests beyond counts.
- **Acceptance:**
  1. A unit-free check: `uv run python scripts/maint/live_eval.py --help` exits 0.
  2. `--dry-run` prints the N commands it would run.
  3. The integrator runs it once with N=3 against the local endpoint
     (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`) and keeps the summary in `internal-docs/baselines/evals/`.
  4. The skeleton diff was seen failing on a baseline with one event removed.
- **Gate:** `uv run ruff check scripts/maint/live_eval.py && uv run mypy scripts/maint/live_eval.py`
  (if mypy covers scripts; otherwise ruff only), plus the integrator's one live run.

### Phase 50 close (integrator)

- Run the full close budget (the board's rule 5.6) plus `uv run pytest tests/e2e -n auto -q`
  twice in a row, both green, to catch order-dependent flakes.
- Record the lane's wall time, the e2e test count and the journeys covered in ROADMAP's Phase 50
  row.
- Archive this section with `scripts/maint/split_board.py archive`.

## How work runs on this board (read before claiming a card)

1. **One card is one worker run.** Its steps are ordered; each step ends green and committed. A run
   that does not finish parks at its last green commit and the card's Status names what is left; the
   next run continues the same card. A card is never split into sub-cards to make it fit.
2. **Claim.** Set Status to `IN-PROGRESS (@who)`; one owner per card. The worker gets a worktree made
   by hand from the integration branch's current head (`git worktree add -b <branch>
   .claude/worktrees/<card> <sha>`), and its own `DOCKET_HOME` and temp directory in the scratchpad.
3. **Read bounded.** `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`, then
   the card's own read list. Never all of `ROADMAP.md`, `TODO.md`, `CLAUDE.md` or a spec directory.
   A task worktree has no `internal-docs/` (gitignored); a card needs only itself and tracked files.
4. **The layer rule** is ADR 0030's table, enforced by `tests/architecture/`: the contexts are layered
   `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator <
   tasks < hops` and a context imports only those below it; `kernel` imports nothing outside itself;
   a `domain/` is pure; only `interfaces/` talks to the user; `bootstrap.py` is the only module that
   names a concrete adapter. Two invariants never move: every tool call passes `dispatch_tool`
   (`agent/tools/registry.py`), and docket-owned JSON is written only by `platform/store.py`.
5. **The testing budget, the same for every card.**
   1. Per commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
      pytest --co -q` (about 10 s). No test runs.
   2. While iterating: only the tests of what the step changed, by path, each under `timeout 120`.
   3. The card's gate, as the card names it, in a few minutes.
   4. A pure move or rename adds no test: `pytest --co` and `tests/architecture` are its check. A
      behaviour change adds a failing test first, placed by lane (`specs/test-framework.md`).
   5. After each merge the integrator runs the default suite once, in parallel (`uv run pytest -n auto
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 40 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close.
   7. **Stop rule:** a check that fails again after one fix stops the step. Park with the failing line
      and the hypothesis. No third attempt, no "until green", no background process or polling, no
      `git stash` (a WIP commit sets work aside).
   8. **A script is a means, not a deliverable.** A one-shot script (planner, path rewriter,
      converter) exists to save effort on the card's goal. Write it once, run it, review its output,
      and finish by hand whatever it did not cover. If it is wrong after one fix, stop improving it
      and do the remainder by bounded edits. Polishing, generalizing or testing a throwaway script is
      out of scope; it is never committed unless the card says so.
6. **Baselines only shrink.** A baseline file is rewritten (`--write`) only after the violations are
   gone, and its diff is deletions only. A new guard is trusted only after it was seen failing on a
   planted case.
7. **No behaviour change** unless the card says so: the HTTP API 6 tests, the CLI goldens and the
   `docket_runtime` facade stay byte for byte. **No re-export or shim:** a replaced name is
   deleted in the same change, with no alias or compatibility reader.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`;
Phases 46-47 run on `plan/phase-46-structure` until the maintainer integrates it). `main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `fab-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: on a real run, measure which calls repeat before cutting anything.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **The serial no-sandbox run fails 7 tests that pass alone** (`scripts/maint/pytest-without-sandbox.sh
  -q`, found at the Phase 48 close; the same 7 at `d6b16df5` in a clean worktree, so older than
  Phase 48). They are `test_step__step_env.py::TestShape::test_a_secret_store_name_is_refused`, two
  in `tests/integration/hops/test_diff_probe.py::TestHopDiffProbeUnit` and four in
  `tests/integration/sandbox/test_task_credentials.py`; the parallel default suite never orders
  them that way. Hypothesis: an earlier test in the same process leaves a process-wide binding
  changed (a bound port, the credential catalog or the secret-store names). Next: bisect the
  serial order with `-p no:randomly` and the file list before the first failure. Trigger: now,
  since the `no-sandbox` CI job runs this script serially once the branch is pushed.

- **Timing flakes seen once each:** `test_kernel_adoption.py` over its 2 s guard ceiling,
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.

**Runtime and dispatch (from real runs).**

- **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in
  `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; operator-api §6 by design). Trigger: the audit log
  fills with one task's refusals, or a second operator asks. Then resume only when the cause changed.
- **A parked turn is paid twice**: the resumed hop re-sends the whole prompt (4,157 input tokens before
  the park, 8,181 after; 100,573 in the 2026-10-18 joint run). Trigger: a third run that parks on the
  same shape. Then weigh resuming the session over re-running the hop (operator-loop §2 item 6).
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
- **Provider rows lag the models in use:** Anthropic advertises dated ids while the template rows use
  aliases (limits stay `unknown`), and no row prices `claude-sonnet-5-5` or `claude-opus-5-5`
  (`task show` prints `cost: -`). Trigger: a run on an alias id whose window matters, or an operator
  asking for the estimate.
- **Hop language drift:** a resumed step once wrote its report in another language, which became the
  next handoff. Trigger: a second occurrence; then a pod `language` setting.
- **The Lead plans with the codebase path while the Implementer is rooted in the task worktree**
  (`tool.refused` on `read`). Trigger: reproduce with a local-model dispatch in a worktree pod.
- **The prospective budget check ignores cache reads**, so a heavily cached step is refused early.
  Trigger: a real run refused with room left. `glob`/`grep` walk vendored trees before filtering;
  measure before changing.
- **A task's `network: none` cuts the agent turn only**; `verifyCmd` and `run:` steps keep the pod's
  posture (stated in the spec).
- **Cancel over HTTP reports `cancelled` once the stop is requested**; the task stays `running` until
  the executor notices. The slow-stub cancel path has no test.
- **Not examined:** each Phase 45 run's trace carries two `approval_denied` events beside its park.
- **Real-Docker tests exceed their duration ceiling under load** (`test_network_lockdown`,
  `test_sandboxed_exec`, the escape matrix's docker cases): they pass alone. A flake, measured
  2026-10-14.

**Workspace and checks.**

- **`docket setup` without `--fix` writes:** its report re-seeds `WORKFLOW_AUTO.md`
  (`interfaces/cli/commands/setup_check.py`). A check that writes is a defect. Trigger: the next edit
  of that file.
- **A file a check reaches only through `make` or `npm run` is protected only through the default
  files it reads**, and **a gitignored file is invisible to the check**. Trigger: a real gate whose
  script lives behind a target, or a repository that ignores a file its gate reads.
- **Prepare:** only `node_modules` is cached (`.venv` is not relocatable); `node_modules/.cache` is
  read-only in the jail; eviction can break a running task's link (resume prepares again); prepare is
  not cancellable (bounded by `PREPARE_TIMEOUT_S`); `hops/workspace/prepare.py::linked_entries` accepts
  any cache entry, not only the task's codebase. Trigger: a real run that hits one of them.
- **Shell keywords are classified as binaries when unjailed** (`for`, `do`, `done`, `if`, `then`,
  `while` ask in `governance/security`). Trigger: an operator without isolation reports it.

**Configuration.**

- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.
- **A team's skills:** `hops/workspace/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope.

**Channels, inbox and the HTTP API.**

- **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`interfaces/http/server.py:200`).
- **Enabling the `email` channel checks nothing**; with no `to`, `from` or `smtpHost`, every delivery
  fails into the health record. Trigger: an operator enables it.
- **Pending memory entries show in `docket inbox` but not in `GET /inbox`, MCP `inbox`, notifications or
  Telegram `/status`.** Needs an operator-v1 inbox contract bump.
- **`GET /pods` (the list) was not checked** for the invalid-settings failure fixed on `/pods/<p>`.
- **`POST /pods/<p>/apply` with every item skipped writes no `pod.apply` audit entry.**
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.
- **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**
  (`packages/docket-runtime/src/docket_runtime/adapters/`). Trigger: someone reads that usage.

**Prompts and pod state.**

- `hops/application/compose.py::_resolve_hop_instructions` still opens "You are the Implementer..."
  (SOUL says it); recipe roles using `${codebaseOrConfigured}` render a path; `repo_map.SKIPPED_DIRS`
  mirrors `toolbox.SKIPPED_DIRS` (pinned by an equality test); pod read routes do not carry
  `tokenBudget`; the condensation notice carries the call's full path.
- **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`teams/pod.py`); no turn
  reads it today. Trigger: a turn that does.
- **Three readers of the implementer's codebase** (`rg -n "def _pod_codebase|def _codebase|def
  task_diff" src`); one helper when next touched.
- **`memory_update` has no structural telemetry key**; members stamped `POD_TEMPLATE_VERSION` 4 show stale
  to `pod update` by text comparison; `scripts/smoke_workflow.py`'s memory scenario needs a live run.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
