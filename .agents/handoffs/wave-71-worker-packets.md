# Wave 71–75 worker packets — Phase 35, docket in a harness-agnostic factory (D-51)

Coordinator: the session that planned Phase 35 on 2026-09-29.

- **Base commit for Wave 71:** the commit that opened it on `develop`
  (`git log -1 --format=%h -- .agents/handoffs/wave-71-worker-packets.md`; planned on top of
  `6525b52`).
- Each later wave bases on the previous wave's rollup on `develop` (D-52: `develop` integrates,
  `main` only moves for a release).
- One card, one worker, one isolated worktree. The model per card is in the card's `**Model:**`
  field; Haiku cards are written so every decision is already made.
- Decision, reversals, verdict table:
  [docs/adr/0017-docket-in-a-harness-agnostic-factory.md](../../docs/adr/0017-docket-in-a-harness-agnostic-factory.md).
- The card is the contract (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py
  P35-<N>`); this file is the map. **Read §0 and your own packet only.**

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 71 | P35-1, P35-2, P35-3, P35-4 | P35-2, P35-1, P35-3, P35-4 |
| 72 | P35-5, P35-7, P35-8 | P35-8, P35-5, P35-7 |
| 73 | P35-6 | — |
| 74 | P35-9 | — |
| 75 | P35-10 (integrator) | — |

**Why this order.**
- P35-2 merges first in Wave 71 because every later harness card builds through its models.
- P35-8 merges before P35-7 because P35-9 sets `requireVerify` on the ephemeral pod P35-7
  provisions.
- `cli/_harness.py::_run` has exactly one owner per wave (P35-2 → P35-5 → P35-6 → P35-9).
  That is the only reason Waves 73 and 74 hold one card each.

## 0. Rules for every worker

### Isolation and environment
- One branch `p35-<N>-<slug>` in your own worktree, checked out at the wave's base. **Verify
  with `git merge-base HEAD develop`.** Phase 31 and 32 worktrees were created at stale commits
  and had to be re-based.
- Never touch `~/.docket`. Every CLI run sets `export W=$(mktemp -d); export
  DOCKET_HOME=$W/.docket` (two statements: inside one `export`, `$W` is still empty).
  **Never override `HOME`**: it breaks uv's cache. pytest isolates `DOCKET_HOME` through the
  autouse fixture in `tests/conftest.py`.
- **Harness mode refuses `DOCKET_HOME` = the default home and requires `DOCKET_LLM_BASE_URL`.**
  Every harness test sets both to a temp home and a loopback fake. Copy the pattern in
  `tests/integration/test_harness_cli.py`.
- **Never call a real model endpoint and never contact a real vendor host.** Every HTTP target
  in a test is a local `http.server` started on port 0 and stopped in `finally`. The only
  exception is P35-10's live run, and only against `127.0.0.1:8081`.
- Patterns to copy:
  - `_ScriptedBackend` in `tests/integration/test_dispatch.py` and in
    `tests/integration/test_docket_driver.py` (a fake model with scripted replies);
  - the subprocess harness driver in `tests/integration/test_harness_cli.py`;
  - fixture validation against the committed schema in
    `tests/integration/test_harness_contract.py`.
- **Never `git stash`**; the stash is shared across worktrees and sessions. Set work aside with
  a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`. Run `env -u VIRTUAL_ENV uv sync --extra
  mcp` once in your worktree first (`scripts/gen_cli_docs.py` imports `click`, which only the
  `mcp` extra brings).

### Order of work
1. Read the owning spec **section** and the neighbouring tests.
2. Write your requirements under **your own new section heading**, numbered from 1 inside it.
   In `specs/api/harness-mode.spec.md`, replace only your own `Planned — owned by P35-N` stub
   (P35-2 creates the stubs).
3. **Never touch `**Version**`, `**Status**`, `**Last Updated**` or a changelog.** The
   integrator bumps each spec once per rollup.
4. Write the RED test and see it fail on the base for the reason the card states.
5. Write the smallest implementation.
6. Run the gates.

### The contract rule (ADR 0017, the W30 seam lesson)
- `--contract 1.0` is the default and **byte-identical** to the base. The four fixtures under
  `tests/fixtures/harness-contract/v1/` and `docs/contracts/harness-v1/schema.json` are the
  no-change oracle for every card. If any of them changes, stop and return the contention.
- Every v1.1 wire value is built through the models in `core/harness.py` (P35-2). Never
  hand-build a result or answer dict in `cli/`.
- Answers use the MCP elicitation result shape (`action: accept|decline|cancel`, `content`).
  Do not invent a synonym.

### Security invariants
- **Fail closed.** An unanswered approval denies at its deadline. A malformed answer line is
  ignored (one stderr line), never interpreted. A malformed `--policy` file refuses the run
  before it starts.
- Every string a human sends to an agent passes `pre_input` through the same evaluation
  `/delegate` uses: `core.policy.policy_eval_detail("lead", "pre_input", text, trusted=False)`.
- Every approval resolution is audited with its channel (`harness` for stdin).
- Verify output stored as evidence passes `core.trace.redact` first. A stored secret value
  never appears in a hop record: prove it with a canary.
- A credential **value** never enters a document, fixture, template, test string or error
  message; credential **names** are fine.

### No new dependency
- `pyproject.toml` is forbidden. Use the stdlib. If a card seems to need a package, stop and
  return the contention.

### Layer rules
- `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never prints, never
  runs a subprocess. Git and process work goes through `edges/adapters/system.py` or
  `edges/adapters/toolbox.py`.
- Docket-owned JSON goes only through `edges/store.py`. Every tool call goes through
  `core/tools.py::dispatch_tool`. P35-3 adds one `ToolContext` field and edits the `bash`
  handler lambda, **nothing else in `core/tools.py`**.
- `cli/_harness.py` writes only NDJSON to stdout; every human word goes to stderr.

### Forbidden files, for every card unless its row in TODO.md's wave table names them
- Central files: `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `pyproject.toml`, `.github/`.
- `docs/`, except `docs/contracts/harness-v1.1/` (P35-2, generated) and regenerating
  `docs/commands.md` (`scripts/gen_cli_docs.py`). Return the README/CHANGELOG line you would add
  instead of writing it.
- `docs/adr/`: the integrator only.
- Never edit `scripts/metrics.py` or `scripts/validate-specs.sh`.
- **Never add a line to `cli/__init__.py::cmd_pod`** (it sits at the 150-line function-span
  ratchet).

### Goldens
- `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` stays byte-identical. No Phase 35
  card changes a golden. If yours does, stop and return the contention.

### Worker gates before returning

```bash
env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src
env -u VIRTUAL_ENV uv run pytest -q
env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
bash scripts/validate-specs.sh
env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check
env -u VIRTUAL_ENV uv run python scripts/gen_config_schemas.py --check
env -u VIRTUAL_ENV uv run python scripts/gen_operator_schemas.py --check
env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <every .py you touched>
env -u VIRTUAL_ENV uv run pytest -q tests/guards
```

- From Wave 72 on, the harness schema pin test covers both v1 and v1.1 (P35-2).
- `scripts/metrics.py --check` is expected to fail on a branch that adds tests or a spec; say
  so.
- Guards apply to every new module:
  - `tests/guards/test_function_span.py` (150 lines per function; `cli/_harness.py::_run` is
    already long, so **extract helpers rather than grow it**);
  - `test_no_print_in_core_edges.py`;
  - `test_no_subprocess_in_core.py`.
- `tests/guards/test_layout.py` may need its baseline **shrunk**, never widened, when a new
  module appears. Say what changed.
- Docstrings are at most three lines. No card ids, wave numbers or dates in any `.py`, `.yaml`
  or `.json` file (`comment_lint.py` refuses them).

### Commit
- One commit per card. Subject `Type: description` (`Add:`/`Fix:`/`Docs:`), ASCII. The body
  says what was false or missing and what is now true.
- **No AI mention, no `Co-Authored-By` trailer of any kind.**
- Before committing, this must print nothing:
  `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-|whsec_[A-Za-z0-9+/]{20,}'`
  (`task-`/`risk-` are false positives for `sk-`).
- Do not push. Do not merge into `develop` or `main`; the integrator merges into `develop`.

### Return (1,500–3,000 characters, no logs)
- card / branch / commit; outcome;
- user-visible behaviour;
- changed paths and owned functions;
- spec sections, with one changelog line per spec for the integrator;
- README/CHANGELOG lines for the integrator;
- RED evidence (test id and the base failure reason);
- focused tests → result; worker gates → pass, or the first failing gate;
- goldens changed (expected: none);
- missing/failed; pending in this card; later follow-ups (locators only);
- contention note: which other card in your wave touches a neighbouring symbol, and that you
  did not.

Symbols below were located at `6525b52` and drift. **Re-locate every one with `rg -n` before
editing.**

---

## P35-1 — two measured defects (Wave 71, Haiku)

Branch `p35-1-guardrail-action-pod-budget`. Allowed:
- `src/docket/core/dispatch.py`: only `_enqueue_pre_input_gate`, `_apply_output_guardrails`,
  and the single `_ctx.budget_for_role(role)` call inside `_hop_message`;
- `src/docket/core/context.py::budget_for_role`;
- `src/docket/core/session.py`: the single `_context.budget_for_role(role)` call;
- `specs/functional/role-archetypes.spec.md` (new section "Pod-scoped token budgets");
- `tests/unit/core/test_context.py`, `tests/integration/test_dispatch.py` (one test each).

Steps, all decided:
1. In both `guardrail_block` payloads replace `"action": hit.policy_id` with `"action":
   hit.action`. Leave `"policy": hit.policy_id` as is.
2. `budget_for_role(role, *, project: str = "", context_window_tokens=None,
   max_output_tokens=None)`: call `_arch.load_registry(project)` when `project` is non-empty,
   else `_arch.load_registry()`. Confirm `load_registry` accepts a project first
   (`rg -n "def load_registry" src/docket/core/archetypes.py`). If it does not, stop and return
   the contention.
3. `_hop_message`: pass the dispatch context's project (the `ctx.project` in scope there).
   `core/session.py`: pass the project the surrounding function already has. If it has none,
   leave that call unchanged and report it.
4. Tests:
   - apply a pod-scoped role with `tokenBudget: 1234` through the same helper the existing
     pod-overlay tests use (`rg -n "tokenBudget" tests/`), then assert `budget_for_role(...,
     project=pod) == 1234`;
   - a `pre_output` block policy on a scripted dispatch writes `guardrail_block` with
     `action == "block"`.
- **RED:** the budget test returns the built-in value on the base.

## P35-2 — the harness contract v1.1 (Wave 71, Sonnet)

Branch `p35-2-harness-contract-v11`. Allowed:
- `src/docket/core/harness.py`;
- `scripts/harness_schema.py`;
- `docs/contracts/harness-v1.1/schema.json` (new, generated);
- `tests/fixtures/harness-contract/v1.1/*.ndjson` (new);
- `src/docket/cli/_harness.py`: `_flag`, `_usage_error`, and the version selection in `_run`
  (where `harness.HarnessEvent(...)` and `result_from` are built), plus the usage string in
  `run_harness`;
- `specs/api/harness-mode.spec.md` (new section "Contract 1.1" only);
- `tests/unit/core/test_harness.py`, `tests/integration/test_harness_contract.py`,
  `tests/integration/test_harness_cli.py`.

Read first:
- `core/harness.py` whole (246 lines);
- `scripts/harness_schema.py` (how `$defs` are hoisted);
- the existing schema-pin and fixture-validation tests.

Design (decided):
- **Versions.** Keep `HARNESS_CONTRACT_VERSION = "1.0.0"` and the v1.0 classes untouched, so
  the v1 schema is byte-identical. Add `HARNESS_CONTRACT_V11 = "1.1.0"` and
  `HARNESS_CONTRACT_VERSIONS`. Implement v1.1 as subclasses or siblings (`HarnessEventV11`,
  `HarnessResultV11`) whose `v` validator requires `"1.1.0"` exactly.
- **New models:**
  - `FileChange` (`path: str`, `op: Literal["write", "edit", "delete", "unknown"]`);
  - `AnswerLine`, with nested `Answer`: `approvalToken`/`questionId`, **exactly one set**
    (model validator), `action: Literal["accept", "decline", "cancel"]`, `content: dict |
    None`;
  - `HarnessTask` (`status: str`, `hops: list[dict[str, Any]]`, `evidence: dict | None`,
    `brief: dict | None`);
  - `Limits` (`maxTokens: int | None`).

  `HarnessResultV11` adds `files: list[FileChange] = []`, `task: HarnessTask | None = None`,
  and `limits: Limits = Limits()`.
- **Builders.** A `result_from_v11(turn, usage, run, *, files=(), task=None, limits=None)`
  builder next to `result_from`, reusing its mapping. A `refusal_result(reason, *,
  version="1.0.0")` that can stamp either version.
- **Schema.** `scripts/harness_schema.py` writes both schema files. The v1.1 file's
  `definitions` include `HarnessEvent`, `HarnessResult` and `AnswerLine`, with the same `$defs`
  hoisting.
- **Fixtures.** Hand-authored, realistic, each line valid against the committed v1.1 file.
  `answer-lines.ndjson` holds only `AnswerLine`s.
- **CLI.** `--contract` accepts `1.0` or `1.1` (default `1.0`); anything else →
  `_refuse(...)` exit 2. Stamp the chosen version on every line of the run, including the
  refusal line when the flag parsed. No behaviour beyond the version stamp.
- **Spec.** A new "Contract 1.1" section: the version rule, the field tables for the new
  models, and **stub subsections**, each "Status: Planned — owned by P35-N":
  - "Process lifecycle events" (P35-3);
  - "Answers on stdin" (P35-5);
  - "Written paths, token file and caller limits" (P35-6);
  - "Recipe runs" (P35-9).
- **RED:** a test that loads `docs/contracts/harness-v1.1/schema.json` and compares it with the
  generated content fails on the base (file missing).

## P35-3 — process lifecycle events (Wave 71, Sonnet)

Branch `p35-3-process-events`. Allowed:
- `src/docket/edges/adapters/toolbox.py::run_bash` (and its private helpers `_kill_group`,
  `_wait_cancellable` only if the exit callback needs a hook there);
- `src/docket/core/tools.py`: the `ToolContext` dataclass (one field `on_process`) and the
  `bash` built-in's handler lambda (`rg -n '"bash"' src/docket/core/tools.py`);
- `src/docket/core/trace.py::EVENT_TYPES` (+2);
- `src/docket/core/telemetry.py::_STRUCTURAL_KEYS` (+2 entries);
- `src/docket/edges/adapters/docket_runtime.py`: the `ToolContext(...)` construction only;
- `specs/functional/trace-store.spec.md` (new section "Process lifecycle events");
- `tests/unit/edges/adapters/test_toolbox.py` (new, `SUBJECT =
  "docket.edges.adapters.toolbox"`), `tests/integration/test_bash_cancellation.py` (one test).

Design (decided):
- `on_process(kind: Literal["started", "exited"], data: dict)` is called:
  - with `started` right after a successful `Popen`, `{"pgid": proc.pid}`;
  - with `exited` exactly once per start, on every path: normal and non-zero give
    `{"pgid", "exitCode"}`; timeout and cancellation give `{"pgid", "signal": "SIGKILL"}`.

  A `Popen` `OSError` produces no event. A `try/finally` around the wait is the simplest way
  to guarantee "exactly once".
- The handler lambda in `core/tools.py` wraps `ctx.on_process` so `tool` and `callId` are
  added. Check what the lambda receives before assuming the call id is in scope; if it is not,
  pass `tool` only and report it.
- `docket_runtime.py`: build the callback. It calls
  `core.trace.trace_event(project, session_key, role, "process_<kind>", json.dumps(data))` with
  the same project/session/role the turn traces under (re-locate how other events there
  resolve them). Then, when `core.runs.current_run_id()` is set, `add_hop_pid(run_id, pgid)`
  on start and `remove_hop_pid(run_id, pgid)` on exit.
- `_STRUCTURAL_KEYS` entries follow the existing tuple shape for neighbouring events.
- **RED:** `run_bash(..., on_process=cb)` raises `TypeError` on the base.
- The integration test runs a turn under a run with `sleep 30`, then calls
  `core.runs.cancel_run(run_id)` from another thread. It asserts the group is dead and
  `process_exited` has `signal`. Use the existing cancellation test's structure.

## P35-4 — hop evidence (Wave 71, Sonnet)

Branch `p35-4-hop-evidence`. Allowed:
- `src/docket/core/dispatch.py`: `_evaluate_mechanical_gate`, `_implementer_diff_probe`, the
  `HopResult` dataclass, `_hop_record`, `_hop_from_record`, and the one call site that builds
  `HandoffArtifact(files_changed=..., diff_ref=...)` from the probe (extend its tuple unpacking
  only);
- `src/docket/edges/adapters/system.py` (three new functions next to `git_changed_files`);
- `specs/functional/pod-dispatch.spec.md` (new section "Hop evidence");
- `tests/integration/test_dispatch.py`, `tests/unit/edges/adapters/test_system.py` (create it
  with `SUBJECT` if missing).

Design (decided):
- New config constant `VERIFY_EVIDENCE_TAIL_CHARS = 4000` in `src/docket/config.py`. This is
  the one allowed edit there.
- `_evaluate_mechanical_gate`:
  - time the `run_verify_cmd` call with `time.monotonic()`;
  - build `verify = {"cmd": verify_cmd, "exitCode": 0 if passed else <code>, "durationS":
    round(d, 3), "outputTail": redacted[-VERIFY_EVIDENCE_TAIL_CHARS:]}` and set `hop.verify =
    verify` before every return that ran the command, including the `routed` return.

  If `run_verify_cmd` does not expose the exit code, use `0`/`1` and report it rather than
  changing `system.py`'s signature.
- The `not verify_cmd` branch is **not yours** (P35-8 owns it next wave). Leave it untouched.
- `system.py`, each degrading to `None` on any failure, like `git_current_branch`:
  - `git_head_sha(cwd) -> str | None`;
  - `git_merge_base(cwd, ref) -> str | None`;
  - `git_diff_stat(cwd, base) -> dict | None` (`--shortstat` parsed into `{files, insertions,
    deletions}`).
- `_implementer_diff_probe` returns an `evidence` dict `{commit, baseCommit, diffStat}`
  alongside the existing pair. `baseCommit` is the merge-base of HEAD with the **codebase's**
  current branch, not the worktree's. Keep the existing two return values' semantics.
- `_hop_record` adds `"verify"` and `"evidence"` (both may be `None`). `_hop_from_record` reads
  them with `.get`, so a base-era record loads unchanged.
- **RED:** a scripted dispatch with `verifyCmd: "echo ok"` has no `verify` key in the
  persisted hop on the base.

## P35-5 — answers on stdin (Wave 72, Sonnet)

Branch `p35-5-harness-answers`. Base: the Wave 71 rollup. Allowed:
- `src/docket/cli/_harness.py::_run` (answer wiring) and the argument helpers P35-2 created;
- `src/docket/cli/_harness_answers.py` (new);
- `src/docket/core/approval.py::approval_create` (the `approval_requested` payload only);
- your stub in `specs/api/harness-mode.spec.md`; `specs/functional/security-gates.spec.md`
  (new section "The harness answer channel");
- `tests/integration/test_harness_cli.py`, `tests/unit/cli/test__harness_answers.py` (new;
  match the existing naming in `tests/unit/cli/`).

Design (decided):
- **Flags:** `--answers stdin` and `--answer-timeout S`.
  - Either one with `--contract 1.0` → exit 2.
  - `--answers stdin` with `--task-file` in (`-`, `/dev/stdin`, `/proc/self/fd/0`) → exit 2
    with a reason naming the conflict.
- **Mode:** `env = {DOCKET_APPROVAL_MODE: "wait"}` under `--answers stdin`, else `"refuse"`.
  The wait timeout: find how `wait_for_approval` reads `TOOL_APPROVAL_TIMEOUT` (`rg -n
  TOOL_APPROVAL_TIMEOUT src/`). If it is only a module constant, pass the value through the
  same env-dict pattern as `DOCKET_APPROVAL_MODE` (a new constant in `core/runtime_driver.py`,
  popped in `docket_runtime.py`). Report which you did.
- **`_harness_answers.serve(token: str, stop: threading.Event)`**, a context manager that
  starts a daemon thread reading `sys.stdin` line by line:
  - Parse with `core.harness.AnswerLine.model_validate_json`. On `ValidationError`, or a
    `token` other than the run's, write one stderr line and continue.
  - For `approvalToken`:
    - if `content` is present, serialise it and run `policy_eval_detail("lead", "pre_input",
      text, trusted=False)`; on a block, write one stderr line and leave the approval pending;
    - `accept` → `approval_grant(t, channel="harness")`;
    - `decline`/`cancel` → `approval_deny(t, channel="harness")`;
    - `ApprovalNoop`/`ApprovalConflict` → one stderr line.
  - For `questionId`: one stderr line, "question answers need --recipe" (P35-9 replaces this).
  - EOF ends the thread quietly.
- **`approval_create`:** add `tool` and `callId` to the `approval_requested` trace payload when
  `context` has them. Nothing else changes.
- **Tests:**
  - the harness test writes the answer line into the subprocess's stdin **after** reading the
    `approval_requested` event from its stdout (two pipes; read with a timeout);
  - the scripted backend's first reply is a `bash` call that a policy asks on, e.g. `git push
    origin production`, which `classify_command` already asks for;
  - the timeout case uses `--answer-timeout 1`.
- **RED:** `--answers` is an unknown argument on the base (exit 2).

## P35-6 — written paths, token file, caller limits (Wave 73, Sonnet)

Branch `p35-6-harness-files-limits`. Base: the Wave 72 rollup. Allowed:
- `src/docket/cli/_harness.py` (new helpers plus their calls in `_run`);
- `src/docket/core/harness.py`: the v1.1 builder's `files`/`limits` arguments only;
- `src/docket/core/runtime_driver.py` (one constant, `DOCKET_TURN_TOKEN_BUDGET`);
- `src/docket/edges/adapters/docket_runtime.py`: pop that key into the loop's token bound
  (re-locate where `LoopConfig` is built);
- `src/docket/edges/adapters/system.py` (one helper `git_status_paths(cwd) -> list[tuple[str,
  str]]` if none exists);
- your stub in `specs/api/harness-mode.spec.md`;
- `tests/integration/test_harness_cli.py`.

Design (decided):
- **`files`:** a collector subscribed through the same `_trace.subscribe` the emitter uses.
  From `tool_call` records whose tool is `write` or `edit`, take the path argument
  (re-locate the argument key in `core/tools.py`'s definitions). `write` → `op="write"`,
  `edit` → `op="edit"`. After the turn, if `git_is_repo(workspace)`, merge the porcelain
  status: `D` → `delete`, otherwise the existing op or `unknown`. Paths are relative to the
  workspace, deduplicated and sorted.
- **`--token-file PATH`:** after `create_run` and before the first `_emit`, write `{"v",
  "token", "pid"}` atomically: temp file in the same directory, `os.chmod(0o600)`, then
  `os.replace`. Pin the stderr line format in the spec.
- **`--max-tokens N`:** a positive int, else exit 2. Pass it via `run_turn`'s env
  `DOCKET_TURN_TOKEN_BUDGET`. The driver pops it into the loop's measured-token bound, never
  as `os.environ`. Echo it in `limits.maxTokens`.
- **`--policy FILE`** (repeatable; `_flag` returns only the first, so add a `_flags` helper):
  - validate each with `core.policy.validate_policy(path)`; a non-empty error → exit 2 before
    `create_run`;
  - copy valid files into the caller home's policy directory (re-locate the constant
    `policy_files()` globs), preserving names, with an `harness-` filename prefix to avoid
    shadowing.
- **RED:** the `files` assertion fails on the base (no such field under v1.1).

## P35-7 — the in-place recipe runner (Wave 72, Sonnet)

Branch `p35-7-inplace-recipe-runner`. Base: the Wave 71 rollup. Allowed:
- `src/docket/core/harness_pipeline.py` (new);
- `src/docket/core/pod_provisioning.py` (the smallest in-place parameter);
- `specs/functional/pod-dispatch.spec.md` (new section "In-place ephemeral pods");
- `tests/integration/test_harness_pipeline.py` (new; `SUBJECT =
  "docket.core.harness_pipeline"` if the integration lane requires one; check a neighbour).

Read first:
- how `docket init` provisions a pod (`cli/_agents.py::run_init` into `core/pod_provisioning.py`);
- how `pod apply` applies a recipe (`core/pod_apply.py::resolve_recipe`, `plan_apply` and the
  function that executes a plan);
- `core/dispatch.py::enqueue_task` and `dispatch_task`'s signatures;
- how `tests/integration/test_dispatch.py` builds a pod with a scripted backend.

Design (decided):
- `run_recipe_task(workspace, recipe, task, *, model, approval_mode, timeout, env) ->
  RecipeRun`, a frozen dataclass: `project`, `task: dict`, `hops: list[dict]`.
- The project id is `h-` + 8 hex characters from `uuid4`, and must pass the core project-id
  validation.
- **Provisioning goes through the same core functions `run_init` uses, not a copy.** If they
  live only in `cli/`, stop and return the contention: moving them is a separate decision.
- **In place:** an Implementer gets no worktree, and its resolved cwd is the codebase
  (`workspace`). Add a keyword like `in_place: bool = False` at the narrowest point in
  `pod_provisioning.py`; the default path is unchanged.
- **Models:** every member's model = `model` (pinned, `modelSource: pinned`).
- **Recipe:** `resolve_recipe(recipe)`, then the plan and apply path `pod apply` uses.
- **Approvals:** set the pod's `approvalMode` to `approval_mode` through `PodSettings` (the
  typed writer), never by raw meta writes.
- **Run:** enqueue, then `dispatch_task` for that task only, synchronously. Return the
  persisted task record and its hops.
- **Out of scope:** `requireVerify` (P35-8 exists in the same wave; the CLI card sets it).
- **RED:** importing `docket.core.harness_pipeline` fails on the base.

## P35-8 — `requireVerify` (Wave 72, Haiku)

Branch `p35-8-require-verify`. Base: the Wave 71 rollup. Allowed:
- `src/docket/core/pod.py::PodSettings` (one field + `KEYS`);
- `src/docket/core/dispatch.py::_evaluate_mechanical_gate`: **only** the `if not verify_cmd:`
  branch;
- `specs/functional/pod-dispatch.spec.md` (new section "Required verification");
- `tests/integration/test_dispatch.py` (two tests), `tests/unit/core/test_pod.py` (one test).

Steps, all decided:
1. `require_verify: bool = Field(False, alias="requireVerify")`, and `"requireVerify"` appended
   to `KEYS` (check whether `KEYS` order is asserted anywhere; append at the end).
2. In the branch, read the pod's settings the way neighbouring code in dispatch reads
   `approvalMode` (re-locate; one read helper exists).
3. If true:
   - trace `verification_failed` with `{"reason": "verification_missing", "member":
     member_id}`;
   - return `_UnitOutcome(kind="failed", hops=[hop], reason="verifyCmd required but not
     set")`.
4. Otherwise the existing code is unchanged, byte for byte.
- `docket pod <p> config set requireVerify true` must work through the existing typed writer;
  add a test if `pod config` has a per-key test table.
- **RED:** with the setting true, the task reaches `done` on the base.

## P35-9 — `harness run --recipe` (Wave 74, Sonnet)

Branch `p35-9-harness-recipe`. Base: the Wave 73 rollup. Allowed:
- `src/docket/cli/_harness.py` (the `--recipe` branch and its helpers);
- `src/docket/cli/_harness_answers.py`: the `questionId` route only;
- `src/docket/core/harness.py`: a `task_block(recipe_run) -> HarnessTask` builder;
- your stub in `specs/api/harness-mode.spec.md`;
- `tests/integration/test_harness_cli.py`, `tests/fixtures/harness-contract/v1.1/` (update
  `recipe-ok.ndjson` only if the real shape differs from P35-2's hand-authored one, and say
  why).

Design (decided):
- **Flag checks:** `--recipe` with `--role` → exit 2; with `--contract 1.0` → exit 2.
- **Run:**
  - `approval_mode` is `wait` under `--answers stdin`, else `refuse`;
  - before dispatch, set `requireVerify: true` on the ephemeral pod through `PodSettings`;
  - wrap the call in the same `_runs.execute` and `_trace.subscribe(_emit)` structure as the
    single-agent path, so cancellation, the token file and process events behave identically.
    Extract a helper rather than duplicate the block.
- **Status mapping:** task `done` → `ok`; `failed` → `failed`; `cancelled` → `cancelled`;
  `waiting_approval` or `waiting_input` at the end → `blocked`, with `blocked` naming the
  approval token or question id and `denial_kind` `approval_unavailable` or `input_required`.
- **Result:** `task_block` copies each persisted hop's `role`, `stepId`, `ok`,
  `artifact.verdict`, `verify` and `evidence`, plus the task's `brief`. `files` is computed as
  in P35-6.
- **`questionId` route:** `core.answers.answer_task(project, task_id, answer, channel=
  "harness", ...)`. Re-locate the real signature. The project and task id come from the
  running recipe context: publish them to the reader through a small shared holder set before
  dispatch.
- **RED:** `--recipe` is an unknown argument on the base.

## P35-10 — integrator (Wave 75)

Not a worker packet. The integrator:
- writes `tests/integration/test_harness_v11_consumer.py` (the seam test in the card);
- runs the live checks against `127.0.0.1:8081` with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`;
- applies the doc corrections the card lists;
- bumps every touched spec once;
- re-trues `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `TODO.md`;
- archives the section;
- writes a short M3 checklist for Tack (four items `present`, each with its commit).
