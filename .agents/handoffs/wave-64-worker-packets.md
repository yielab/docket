# Wave 64–70 worker packets — Phase 34, the operator loop (D-50)

Coordinator: the session that planned Phase 34 on 2026-09-28.

- **Base commit for Wave 64:** the commit that opened it on `main`
  (`git log -1 --format=%h -- .agents/handoffs/wave-64-worker-packets.md`; planned at
  `0197e8b`).
- Each later wave bases on the previous wave's rollup.
- One card, one worker, one isolated worktree. The model per card is in the card's `**Model:**`
  field; Haiku cards are written so every decision is already made.
- Decision, standards, the A2A table and the cut/deferred lists:
  [docs/adr/0016-operator-loop-and-interop-standards.md](../../docs/adr/0016-operator-loop-and-interop-standards.md).
- The card is the contract (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py
  P34-<N>`); this file is the map. **Read §0 and your own packet only.**

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 64 | P34-1, P34-2, P34-3, P34-4 | P34-2, P34-3, P34-4, P34-1 |
| 65 | P34-5, P34-6, P34-7 | P34-5, P34-7, P34-6 |
| 66 | P34-8, P34-9 | P34-8, P34-9 |
| 67 | P34-10, P34-11 | P34-10, P34-11 |
| 68 | P34-12, P34-13, P34-14 | P34-12, P34-13, P34-14 |
| 69 | P34-15, P34-16 | P34-15, P34-16 |
| 70 | P34-17 (integrator) | — |

## 0. Rules for every worker

### Isolation and environment
- One branch `p34-<N>-<slug>` in your own worktree, checked out at the wave's base. **Verify
  with `git merge-base HEAD main`**: Phase 31 and 32 worktrees were created at stale commits
  and had to be re-based.
- Never touch `~/.docket`. Every CLI run sets `export W=$(mktemp -d); export
  DOCKET_HOME=$W/.docket` (two statements: inside one `export`, `$W` is still empty).
  **Never override `HOME`**: it breaks uv's cache. pytest isolates `DOCKET_HOME` through the
  autouse fixture in `tests/conftest.py`.
- **Never call a real model endpoint and never contact a real vendor host.** Every HTTP target
  in a test is a local `http.server` started on port 0 and stopped in `finally`. The only
  exception is P34-1's `--live-model` mode, and only against `127.0.0.1:8081`.
- Patterns to copy:
  - `_ScriptedBackend` in `tests/integration/test_dispatch.py` (a fake model with scripted
    replies);
  - the same class in `tests/integration/test_docket_driver.py`;
  - the loopback endpoint in `scripts/smoke_workflow.py`.
- **Never `git stash`**; the stash is shared across worktrees and sessions. Set work aside with
  a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`. Run `env -u VIRTUAL_ENV uv sync --extra
  mcp` once in your worktree first (`scripts/gen_cli_docs.py` imports `click`, which only the
  `mcp` extra brings).

### Order of work
1. Read the owning spec **section** and the neighbouring tests.
2. Write your requirements under **your own new section heading**, numbered from 1 inside it.
   In `specs/functional/operator-loop.spec.md`, replace only your own stub.
3. **Never touch `**Version**`, `**Status**`, `**Last Updated**` or a changelog.** The
   integrator bumps each spec once per rollup.
4. Write the RED test and see it fail on the base for the reason the card states.
5. Write the smallest implementation.
6. Run the gates.

### Standards are not optional (ADR 0016 §1)
- `a2aState` values are exactly the A2A 1.0.0 names: `SUBMITTED`, `WORKING`,
  `INPUT_REQUIRED`, `AUTH_REQUIRED`, `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`.
- A question is `{message, requestedSchema}` in the MCP elicitation subset. An answer is
  `{action: accept|decline|cancel, content}`.
- Events are CloudEvents 1.0 with `type` `dev.docket.<noun>.<verb>` and `source`
  `urn:docket:pod:<pod>`.
- Webhooks use the Standard Webhooks headers `webhook-id`, `webhook-timestamp` and
  `webhook-signature: v1,<base64>`, where the base64 is an HMAC-SHA256 over `<id>.<ts>.<body>`
  with the base64-decoded `whsec_` secret.
- Do not invent a synonym, a second envelope or a second state vocabulary. Build every value
  through `core/operator_contract.py` (P34-2); never hand-build the same dict twice.

### Security invariants
- **Fail closed.** An expired approval denies. An unanswered question blocks and **never**
  fails. A non-allow-listed actor cannot converse or decide. Email can never decide. A
  notification never carries a control that decides.
- `minimal` content never carries a command line or question text. Every card that renders an
  event asserts this with a canary string.
- Every string a human sends to an agent passes `pre_input`, through the same evaluation
  `/delegate` uses: `core.policy.policy_eval_detail("lead", "pre_input", text, trusted=False)`
  (see `core/telegram.py`).
- A credential **value** never enters a document, fixture, template, test string or error
  message; credential **names** are fine.

### No new dependency
- `pyproject.toml` is forbidden. Use the stdlib: `urllib`, `json`, `hmac`, `hashlib`, `base64`,
  `smtplib`, `subprocess` (edges only). If a card seems to need a package, stop and return the
  contention.

### Layer rules
- `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never prints, never
  opens a socket, never runs a subprocess and never imports `edges/`. A `core` function that
  delivers receives a sink factory from its caller (the `core/telemetry.py::start(specs,
  sink_for)` pattern).
- Docket-owned JSON goes only through `edges/store.py`. Every tool call goes through
  `core/tools.py::dispatch_tool` (P34-5 edits its `ask` branch and nothing else).

### Forbidden files, for every card unless its row in TODO.md's wave table names them
- Central files: `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `pyproject.toml`, `.github/`.
- `docs/`, except regenerating `docs/commands.md` (`scripts/gen_cli_docs.py`), the schemas
  under `docs/contracts/config-v1/` (`scripts/gen_config_schemas.py`) and `docs/recipes.md`
  (`scripts/gen_recipe_docs.py`). Return the README/CHANGELOG/CONFIGURATION line you would add
  instead of writing it.
- Never edit `scripts/metrics.py` or `scripts/validate-specs.sh`.
- **Never add a line to `cli/__init__.py::cmd_pod`**: it sits exactly at the 150-line
  function-span ratchet. Pod subcommands go in `cli/_pod.py::dispatch`'s table; the integrator
  reconciles the help text.

### Goldens
- `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` stays byte-identical unless your
  card names the change. If it does, regenerate only that case and list every changed line with
  its reason.

### Worker gates before returning

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

- From Wave 65 on, also run `env -u VIRTUAL_ENV uv run python scripts/gen_operator_schemas.py
  --check`.
- `scripts/metrics.py --check` is expected to fail on a branch that adds tests or a spec; say
  so.
- Guards apply to every new module:
  - `tests/guards/test_function_span.py` (150 lines per function);
  - `test_no_print_in_core_edges.py`;
  - `test_no_subprocess_in_core.py`.
- `tests/guards/test_layout.py` may need its baseline **shrunk**, never widened, when a new
  module appears. Say what changed.
- Docstrings are at most three lines. No card ids, wave numbers or dates in any `.py` or
  `.yaml` file (`comment_lint.py` refuses them). The one allowed exception is P34-7's refusal
  message text, which P34-10 deletes.

### Commit
- One commit per card (P34-8 may use two). Subject `Type: description` (`Add:`/`Fix:`/`Docs:`),
  ASCII. The body says what was false or missing and what is now true.
- **No AI mention, no `Co-Authored-By` trailer of any kind.**
- Before committing, this must print nothing:
  `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-|whsec_[A-Za-z0-9+/]{20,}'`
  (`task-`/`risk-` are false positives for `sk-`; a test's `whsec_` fixture must be visibly
  fake, e.g. `whsec_dGVzdA==`).
- Do not push. Do not merge into `main`.

### Return (1,500–3,000 characters, no logs)
- card / branch / commit; outcome;
- user-visible behaviour;
- changed paths and owned functions;
- spec sections, with one changelog line per spec for the integrator;
- README/CHANGELOG/CONFIGURATION lines for the integrator;
- RED evidence (test id and the base failure reason);
- focused tests → result; worker gates → pass, or the first failing gate;
- goldens changed;
- missing/failed; pending in this card; later follow-ups (locators only);
- contention note: which other card in your wave touches a neighbouring symbol, and that you
  did not.

Symbols below were located at `0197e8b` and drift. **Re-locate every one with `rg -n` before
editing.**

---

## P34-1 — the operator-loop scenario (Wave 64, Sonnet)

Branch `p34-1-operator-loop-scenario`. Allowed: `scripts/smoke_workflow.py`; `tests/` only for
the single isolation fix, if you find one. Forbidden: everything under `src/`.

- **Read first.** `scripts/smoke_workflow.py`'s module docstring, its argument parser, and how
  an existing `--scenario` builds its loopback endpoint and scripted replies. Add
  `operator-loop` as one more scenario. Do not restructure the file.
- **Scripted replies.** Every hop needs a scripted chat-completions reply:
  - the Lead's plan text;
  - for A1, an Implementer tool call `{"name": "bash", "arguments": {"command": "git push
    origin main"}}`. The `prod-approval` policy asks on it; confirm with `docket policies test
    pre_tool_call implementer "git push origin main" --pod alpha`;
  - replies to any retries.

  The endpoint must answer deterministically by matching the incoming messages, never by call
  order alone: a retry changes the order.
- **Serve.** Start `docket serve --dispatch -i 1` as a subprocess on a free port with the
  throwaway `DOCKET_HOME`. Poll `GET /tasks` (Bearer from `serve.token` in that home) until
  every task is terminal or `waiting_*`, with a 90 s ceiling. Then SIGTERM it.
- **Measurements.** Read `sweepBlockedSeconds` from the trace JSONL under
  `$DOCKET_HOME/traces/`: the `ts` of alpha's `approval_requested` against the `ts` of beta's
  first `session_start`.
  - `leadAsked` is `true` iff any task was ever `waiting_input`. It is always `false` at the
    base.
  - `eventsDelivered` counts deliveries recorded in `channels-health.json` when present, else
    `0`.
- **Real-home guard.** `os.stat` `$HOME/.docket/audit.log` (if it exists) before and after;
  fail the scenario if size or mtime changed.
- **The `proj` pollution hunt.** `command grep -rn '"proj"' tests/ scripts/` (plain `grep` is
  aliased to ripgrep and skips gitignored files). Look for a test that creates approvals or
  runs cancellation without the autouse `DOCKET_HOME` fixture: a subprocess test that does not
  pass `env`, or a module-level `docket.config` import cached before the fixture. The entries
  are all from 2026-09-25, with channels `cli` and `cancellation`. Report the file and test id.
  Fix only if it is one isolation line inside `tests/`.
- **RED:** `env -u VIRTUAL_ENV uv run python scripts/smoke_workflow.py --scenario
  operator-loop` fails on the base with the parser's invalid-choice error.

## P34-2 — the `operator-v1` contract (Wave 64, Sonnet; Haiku-capable)

Branch `p34-2-operator-contract`. Allowed:
- `src/docket/core/operator_contract.py` (new);
- `scripts/gen_operator_schemas.py` (new);
- `docs/contracts/operator-v1/*.schema.json` (new, generated);
- `specs/functional/operator-loop.spec.md` (new);
- `tests/unit/core/test_operator_contract.py` (new, `SUBJECT = "docket.core.operator_contract"`).

Model every field exactly as follows. `camelCase` aliases on the wire use
`populate_by_name=True` with `alias=...`, as `core/conversations.py` does.

- **`A2A_STATES`**: a tuple of the eight names in the order of ADR 0016 §3.
- **`a2a_state(status, blocked_reason=None, failure_kind=None)`**:
  - `pending` → `SUBMITTED`; `running` → `WORKING`;
  - `waiting_input` and `waiting_approval` → `INPUT_REQUIRED`;
  - `blocked` → `AUTH_REQUIRED` if `blocked_reason == "resources"`, else `INPUT_REQUIRED`;
  - `done` → `COMPLETED`;
  - `failed` → `REJECTED` if `failure_kind == "rejected"`, else `FAILED`;
  - `cancelled` → `CANCELED`;
  - anything else raises `ValueError`.
- **`TaskBrief`** (`extra="forbid"`):
  - `objective: str` (required, non-empty);
  - `acceptance: list[str] = []`, `context: list[str] = []`, `constraints: list[str] = []`,
    `assumptions: list[str] = []`, `questions: list[str] = []`;
  - `resources: list[str] = []`: each entry `secret:<NAME>`, `path:<p>` or `verify`; validate
    the prefix;
  - `expected_risky_actions: list[str] = []` (alias `expectedRiskyActions`);
  - `answers: list[dict[str, Any]] = []`.
- **`QuestionSchema`**: validate a raw dict, as specified in the card. Keep it a function
  `validate_requested_schema(d) -> dict`, plus a Pydantic wrapper for the schema generator.
- **`Question`**: `id` (`q-<uuid4 hex[:12]>` minted by callers, not by the model), `task_id`,
  `pod`, `step`, `message`, `requested_schema`, `created_at`, `expires_at`.
- **`AnswerResult`**: `action: Literal["accept", "decline", "cancel"]`,
  `content: dict[str, Any] | None = None`.
- **`validate_answer(question, result) -> AnswerResult`**:
  - `accept` requires every `required` property, with a type match (string/number/integer/
    boolean, and enum membership);
  - `decline` and `cancel` ignore `content`;
  - raises `ValueError` naming the property.
- **`ApprovalView`**: `token`, `pod`, `task_id: str | None`, `role`, `tool: str | None`,
  `action: str | None` (the rendered command; callers null it at `minimal`), `policy: str |
  None`, `state`, `created_at`, `expires_at: str | None`, `a2a_state` (always
  `INPUT_REQUIRED` while pending).
- **`TaskView`**: `id`, `pod`, `status`, `a2a_state`, `reason`, `description`, `priority`,
  `created_at`, `updated_at`, `question: Question | None`, `approval_token: str | None`,
  `brief: TaskBrief | None`.
- **`InboxView`**: `needs_you: list[TaskView | ApprovalView]`, `failed: list[TaskView]`,
  `done_since: list[TaskView]`, `running: list[TaskView]`, `next: str | None`.
- **`CloudEvent`**: `specversion: Literal["1.0"] = "1.0"`, `id`, `source`, `type`, `time`,
  `subject`, `datacontenttype: Literal["application/json"] = "application/json"`, `dataschema`,
  `data: dict[str, Any]`.
  - `make_event(kind, pod, subject, data, *, time, version)` sets `type =
    "dev.docket." + kind`, `source = f"urn:docket:pod:{pod}"`, `id =
    sha256(f"{type}|{subject}|{version}")[:32]`, and `dataschema =
    "https://docket.dev/schemas/operator-v1/event.schema.json"`.
- **`EVENT_KINDS`**: `task.input_required`, `approval.requested`, `approval.expiring`,
  `task.blocked`, `task.failed`, `task.rejected`, `task.completed`, `channel.test`.
- **`canonical_args_digest`**: exactly as the card says.

**Generator.** Copy `scripts/gen_config_schemas.py`'s shape (`--check`, the `$id` injection,
`sort_keys`, trailing newline). Write only under `docs/contracts/operator-v1/`, with no
package copy. Name the files `task`, `question`, `answer`, `approval`, `inbox`, `brief`,
`event`.

**Spec.**
- Copy the header block of `specs/functional/session-history.spec.md`: Version `0.1.0`, Status
  `Draft — contract only; behaviour ships across Phase 34`.
- Sections: Purpose, Scope, Requirements (with the nine subsections listed in the card, eight
  of them stubbed `Status: Planned — owned by P34-N.`), Interface Contracts, Examples,
  Validation, Changelog.
- Must pass `bash scripts/validate-specs.sh`. Do not edit `specs/README.md`; return the index
  line instead.

## P34-3 — the Lead's truth fix (Wave 64, Haiku)

Branch `p34-3-lead-truth`. Allowed:
- `src/docket/core/archetypes.py`: only the `_LEAD_BODY` string;
- `docs/AGENT-TEAMS.md`: only the Lead row of the roles table, the line containing `| **Lead**
  |`;
- `tests/integration/test_pod_role_workspace_parity.py`;
- `tests/integration/test_legacy_role_parity.py`;
- any golden case whose expected output contains `human communication`
  (`command grep -rln "human communication" tests/`);
- `specs/functional/role-archetypes.spec.md`, only if it quotes the old lines.

Steps, in order:
1. `rg -n "human communication|Surface architectural" src tests specs docs`. Write the list
   down.
2. Edit `_LEAD_BODY`. Replace the line `"- You own the pod's context, memory, and human
   communication.\n"` with the card's first line, and `"- Surface architectural decisions and
   risky actions to the human (HITL).\n"` with the card's second line. Keep the `"...\n"`
   string-literal style and the other lines byte-identical.
3. Run the two parity tests. They must fail, showing only those two lines. This is your RED
   evidence; paste the test id and the one-line reason.
4. Update the expected text in each test and golden to the new lines. Do not change anything
   else in those files.
5. Edit the `docs/AGENT-TEAMS.md` Lead row's third cell to the card's text.
6. Run the gates. In the commit body, list each changed expected line and say: "the old text
   told the Lead it owns human communication; no path lets the Lead message a human".

## P34-4 — foreground progress and the in-place prompt (Wave 64, Sonnet)

Branch `p34-4-foreground-progress`. Allowed:
- `src/docket/cli/_pod.py` (`_pod_dispatch`, `_parse_dispatch_args`);
- `src/docket/cli/_progress.py` (new);
- `tests/unit/cli/test_pod.py`, `tests/unit/cli/test_progress.py` (new, `SUBJECT =
  "docket.cli._progress"`);
- `specs/api/cli-interface.spec.md` (new section);
- `docs/commands.md` (regenerate).

Forbidden: all of `src/docket/core/`, and `serve.py`.

- `core.trace.subscribe(sink)` is a context manager (`core/trace.py`). Sinks run
  **synchronously inside `trace_event`, on the writer's thread**, so your sink must only
  `queue.put_nowait` and never block. See `cli/_harness.py::_emit` for the existing consumer.
- Run `dispatch_pod(...)` in a `threading.Thread`. The main thread loops on
  `queue.get(timeout=0.2)` until the thread finishes, then renders the existing summary exactly
  as today.
- The `approval_requested` payload carries `token` and `action`: read
  `core/approval.py::_emit_trace`'s call in `approval_create`. The countdown is
  `config.TOOL_APPROVAL_TIMEOUT` minus the elapsed time since the event.
- **The prompt.** Use a second thread that reads `sys.stdin.readline()`, or a `select` on
  stdin; keep it simple and test it with an `io.StringIO` injected through a parameter. On `a`,
  call `core.approval.approval_grant(token, channel="cli")` and then
  `core.dispatch.resolve_waiting_approval(token, "granted")`, the same pair
  `cli/_approve.py::run_approve` uses. Catch `ApprovalNoop` (someone answered elsewhere): print
  one dim line and continue.
- **TTY detection** is injectable (parameters defaulting to `sys.stderr.isatty` and
  `sys.stdin.isatty`) so tests never need a pty. `--progress` forces rendering; `--no-prompt`
  disables the prompt. Parse both in `_parse_dispatch_args`, whose return type grows: update
  its one other caller.
- **The no-change oracle.** With no TTY and no `--progress`, the code path must not start a
  thread or subscribe. Goldens stay byte-identical.

## P34-5 — park and single-use pre-grants in the chokepoint (Wave 65, Sonnet)

Branch `p34-5-park-pregrant`. Allowed:
- `src/docket/core/tools.py`: `ToolContext`, the `ask` branch of `dispatch_tool`, and a new
  frozen dataclass `Pregrant`;
- `src/docket/core/approval.py`: new `create_pregrant`, `consume_pregrant`, and `expiresAt`
  handling in `approval_sweep_expired`;
- `src/docket/core/agent_loop.py`: the stop handling next to `approval_unavailable`, and a new
  `approval_parked_error`;
- `src/docket/core/runtime_driver.py`: new constants `DOCKET_PREGRANTS` and
  `DOCKET_APPROVAL_EXPIRES_AT`, next to `DOCKET_APPROVAL_MODE`;
- `src/docket/edges/adapters/docket_runtime.py`: the two pops next to `approval_mode_raw =
  tool_env.pop(DOCKET_APPROVAL_MODE, None)`, into `ToolContext.pregrants` and
  `ToolContext.approval_expires_at`;
- tests in `tests/unit/core/test_tools.py`, `test_approval.py`, `test_agent_loop.py`;
- `security-gates.spec.md`, `agent-loop.spec.md` (new sections).

Forbidden: `core/dispatch.py`, `core/pod.py`, `cli/`, `serve.py`, `cli/_harness.py`.

- **The ask branch.** In `dispatch_tool`, find `if ctx.approval_mode == "refuse":` (about line
  366 at the base). Insert the pre-grant check **before** it; insert the `park` branch between
  `refuse` and `approval_create`.
  - `park` must create the record with
    `context={"tool": tool.name, "callId": call.id, "argsDigest": digest, "parked": True}`
    plus, when present on `ctx`, `project`/`role`.
  - It returns without calling `wait_for_approval`.
  - Put the token on the result: add `approval_token: str = ""` to the result dataclass. Read
    `ToolResult` first; the agent loop and the harness `result_from` consume it, so keep the
    change additive.
- **The digest.** Compute it with `core.operator_contract.canonical_args_digest` (P34-2, merged
  first in Wave 64).
- **`consume_pregrant(token)`.** One `edges/store.py::read_modify_write` on the record. It
  returns `True` only if `state == "granted"`, `consumedAt` is absent, and `expiresAt` is
  absent or in the future. It sets `consumedAt` and then calls `audit_log("approval.consume",
  f"token={token} tool={tool}")` after the write.
- **Grant-once semantics for parked records.** A *parked* record granted by a human is also a
  single-use pre-grant: dispatch (P34-8) passes it through `DOCKET_PREGRANTS`, and this card
  consumes it.
- **The expiry sweep.** In `approval_sweep_expired`, use `rec.get("expiresAt")` when present,
  else `created + APPROVAL_TIMEOUT`. Keep `_resolve_timeout_as_denied` as the only terminal
  path. Pre-grants past `expiresAt` are pruned by the same sweep, resolving to `denied`.
- **The agent loop** (about lines 1666–1714 at the base). Treat
  `denial_kind == "approval_parked"` exactly like `approval_unavailable`: stop the loop with
  `stop_reason="approval_parked"`. Add the reason to the stop-reason vocabulary near
  `"approval_unavailable"` (about line 184).
- **The harness contract** (`core/harness.py`, `docs/contracts/harness-v1/schema.json`) must
  not change. The harness always passes `refuse`, so `approval_parked` can never reach it.
  Assert this in the agent-loop test with a comment-free test name.
- **RED:** `ToolContext(approval_mode="park")` raises at the base (the `Literal`), or the call
  waits. Prove it with an injected `sleep` that raises.

## P34-6 — the inbox (Wave 65, Sonnet)

Branch `p34-6-inbox`. Allowed:
- `src/docket/core/inbox.py` (new), `src/docket/cli/_inbox.py` (new);
- one `@app.command("inbox")` stub in `cli/__init__.py` (not in `cmd_pod`);
- `serve.py`: one `elif path == "/inbox"` branch in `do_GET`, and one metrics block;
- `cli/_mcp.py`: a new `tool_inbox`, registered where `tool_approvals_list` is;
- `core/telegram.py`: only the `/status` reply builder;
- `config.py`: one path constant, `INBOX_CURSOR_FILE`;
- tests in `tests/unit/core/test_inbox.py` (new), `tests/unit/cli/test_inbox.py` (new), and
  the existing serve and telegram test files;
- spec sections as in the card;
- `docs/commands.md` (regenerate).

- **Enumerating pods.** Read `core/dispatch.py::dispatchable_pods` and find what it filters.
  The inbox must include paused pods, so use the underlying pod enumeration it builds on.
  Tasks come from `read_tasks(project)`. Approvals come from `core/approval.py::list_pending`.
  Link an approval to a task through its `context.taskId` when present, so it appears once,
  inside its task item.
- **Purity.** `build_inbox` takes `now` and `since` and does no writes. The cursor write lives
  in `cli/_inbox.py`, through `edges/store.py`.
- **Timestamps** are the tasks' ISO strings: `completedAt`, else `startedAt`, else `created`.
  `next` is the maximum over all items.
- **`/status`.** Keep requirement 3: scope to the bound agent's project (read the existing
  scoping helper near `core/telegram.py` line 176). Render `needs_you` first. Keep the reply
  plain text.
- **HTTP.** Copy the Bearer check and the `json.dumps(...).encode()` pattern from the
  `/approvals` branch.
- **RED:** importing `docket.core.inbox` fails at the base.

## P34-7 — the `input` step, format only (Wave 65, Haiku)

Branch `p34-7-input-step-format`. Allowed:
- `src/docket/core/pipeline.py` (`InputSpec`, `Step`, `PipelineSpec` validators, short-form
  normaliser);
- `src/docket/core/orchestrator.py` (plan rendering, and one refusal);
- `docs/contracts/config-v1/pipeline.schema.json` and its package copy (regenerate only);
- `tests/unit/core/test_pipeline.py`, `tests/unit/core/test_orchestrator.py`;
- `pipeline-format.spec.md` (new section).

Steps, in order:
1. Read `class Step` (`core/pipeline.py`, about line 151) and its `_check_shape` validator.
   Read how `run` was added (Phase 28): mirror every place `run` appears
   (`rg -n "\.run\b|\"run\"" src/docket/core/pipeline.py src/docket/core/orchestrator.py`).
2. Add `class InputSpec(BaseModel)`: `model_config = ConfigDict(extra="forbid",
   populate_by_name=True)`; `from_: str = Field(alias="from")`; `message: str = ""`;
   `expires_hours: int | None = Field(None, alias="expiresHours", gt=0)`.
3. Add `input: InputSpec | None = None` to `Step`. In `_check_shape`, if `input` is set, raise
   `ValueError(f"step {self.id!r}: an 'input' step carries no <field>")` for each of `role`,
   `agent`, `run`, `parallel`, `gate`, `retries`, `timeout`, `instructions`, `model` that is
   set.
4. In `PipelineSpec`'s validator, `input.from_` must equal the id of a step **before** this
   one. An input step's `on` keys, lower-cased, must be a subset of `{"answered",
   "declined"}`.
5. In the short-form normaliser, accept a mapping value with key `input`
   (`- ask: {input: {from: triage}}`). Find how `run` short forms are normalised and follow
   that.
6. Plan rendering. Find where `plan` renders a `run` step and add
   `f"{step.id} ← asks the operator (from {step.input.from_})"`.
7. Refusal. Where the orchestrator builds executable planned units, raise the existing error
   type with the message in the card.
8. Regenerate the schemas: `env -u VIRTUAL_ENV uv run python scripts/gen_config_schemas.py`.
9. Tests: one valid document parses and plans; three invalid ones fail with the named message.

## P34-8 — dispatch parks (Wave 66, Sonnet)

Branch `p34-8-dispatch-park`. Two commits are allowed: (a) the settings and defaults, (b) park,
re-entry and expiry.

Allowed:
- `core/dispatch.py`: `pod_approval_mode`, `_compose_hop` (the `DOCKET_APPROVAL_MODE` env line,
  about line 1190), `_execute_unit`, `_UnitOutcome` if needed, `_ResumePosition` and its
  builder (about lines 830–920), `resolve_waiting_approval`, `dispatch_pod`;
- `core/pod.py` (`PodSettings`, the keys map, `RECORDED_KEYS` only if the pattern requires it);
- `serve.py::_run_sweeps` (one argument);
- `cli/_pod.py::_pod_dispatch` (one argument, and the `[p]` key in P34-4's prompt through
  `cli/_progress.py`);
- `cli/_config.py` (the `config explain` line for `approvalMode`);
- tests in `tests/integration/test_dispatch.py` and `tests/unit/core/test_pod.py`;
- specs as in the card;
- goldens, only if `config explain` output changes (list every line).

- **"Unset".** First find how pod settings persist (`rg -n "approvalMode" src/docket/core`).
  If `PodSettings` is rebuilt from stored meta, "unset" = the key is absent from the stored
  dict. Expose `pod_approval_mode_is_set(project) -> bool`, or return `None` from the raw read.
  **Do not** change the field default: `export`/`apply` round-trips and the goldens depend on
  it.
- **Re-entry is the hard part.** Read `_ResumePosition` and how `resume_from` hops rebuild
  `pipeline_index`, `rework_counts` and `route_counts`, and how
  `gateOverridePipelineIndex` is consumed for hop-level approvals.
  - A parked hop must be persisted (so the audit and trace history stays true) with
    `parked: true`, and the builder must **not** count it as a completed step.
  - Resume at its index. The override-index field is for skipping an approval *gate*, not for
    re-running a hop: do not reuse it for this.
  - Write the resume test first.
- **Pre-grants into the hop.** `resolve_waiting_approval(token, "granted")`, for a record whose
  context has `parked: True`, appends `{"token": token, "tool": ctx.tool, "argsDigest":
  ctx.argsDigest}` to the task's `pregrants`, inside the same `read_modify_write`.
  `_compose_hop` serialises the task's unconsumed `pregrants` as JSON into
  `env[_rd.DOCKET_PREGRANTS]`. P34-5 consumes it.
- **Expiry.** P34-5 already pops `DOCKET_APPROVAL_EXPIRES_AT` into
  `ToolContext.approval_expires_at` and writes it as the parked record's `expiresAt`. This card
  only sets that env key in `_compose_hop` (`now + approvalExpiryHours`, ISO UTC). Do not touch
  `core/tools.py`, `core/approval.py`, `core/runtime_driver.py` or `docket_runtime.py`.
- **The sweep test.** Build two pods in one `DOCKET_HOME` and call `serve._run_sweeps(True)`
  directly, with an injected slow `TOOL_APPROVAL_TIMEOUT=60`. Assert it returns in under 5 s
  and pod B's task is `done`.
- **The TTY `[p]` key.** It cancels the in-flight wait through the `cancellation_check` seam.
  If that seam cannot distinguish "park" from "cancel" without touching `core/approval.py`,
  drop the `[p]` key, report it as a follow-up, and do not widen scope.

## P34-9 — `kind: channel` (Wave 66, Sonnet)

Branch `p34-9-channel-kind`. Allowed:
- `core/channel.py` (new), `templates/channels/0N-*.yaml` (new);
- `cli/_channels.py` (new), and one `channels` stub in `cli/__init__.py`;
- `config.py` (`CHANNELS_FILE = DOCKET_HOME / "docket-channels.json"`);
- `core/config_docs.py` (`KINDS`, the validate path, the model map);
- `scripts/gen_config_schemas.py` (`KINDS`);
- `docs/contracts/config-v1/channel.schema.json` and its package copy;
- the package-data glob in `pyproject.toml`: **forbidden**. If templates are not shipped
  without it, check how `templates/exporters` is included (probably a glob already covering
  `templates/**`) and report.
- tests `tests/unit/core/test_channel.py` (new), `tests/unit/cli/test_channels.py` (new);
- specs as in the card; `docs/commands.md`.

- **Mirror, don't import.** Copy the structure of `core/exporter.py`: `ExporterSpec` →
  `ChannelSpec`, `load_catalog`, `_load_builtin_*`, `_load_global_*`, `save_*`, `enable_*`,
  `disable_*`, `export_*`, and the `set_privacy` → `set_content` widening logic with
  `is_widening`. Content order: `minimal < actions < conversation`.
- **Audit.** Reuse the audit detail shape of `exporter.enable` and `exporter.privacy`, as
  `channel.enable`, `channel.disable`, `channel.content`.
- **Built-ins.** Every built-in YAML carries a `description` a newcomer understands. Example
  `05-ntfy.yaml`:
  - `dialect: ntfy`, `capabilities: [notify]`, `on: [needs_you, task.failed]`,
    `content: minimal`, `config: {server: "https://ntfy.sh", topic: ""}`, `enabled: false`;
  - `enable` refuses while `topic` is empty.

  `07-telegram.yaml`: `capabilities: [notify, converse, decide]`, `actors: []`. It stays
  disabled; `enable` refuses without `--set actors=<id>`.
- **Validation errors** name the dotted location (`capabilities[1]`). Follow
  `_validation_to_exporter_error`.

## P34-10 — questions execute (Wave 67, Sonnet)

Branch `p34-10-waiting-input`. Allowed:
- `core/dispatch.py`: `_run_pipeline` (the new branch), a new `_run_input_step`,
  `TaskResult.status` vocabulary, `_apply_result`, `_eligible_for_claim` (exclude
  `waiting_input`), `_hop_message` (the answers section), `retry_task` (accept
  `blocked`/`input_expired`);
- `core/orchestrator.py` (remove P34-7's refusal; `PlannedUnit` gains `input`);
- `core/answers.py` (new);
- `core/trace.py::EVENT_TYPES`;
- `core/telemetry.py::_STRUCTURAL_KEYS` (two entries: `input_requested` →
  `("task", "step", "questionId")`, `input_answered` → `("task", "step", "questionId",
  "action")`);
- `serve.py::_run_sweeps` (one call);
- tests in `tests/integration/test_dispatch.py`, `tests/unit/core/test_answers.py` (new);
- specs as in the card.

- **The synthetic hop.** When an answer is consumed, persist a `HopResult(role="operator",
  member_id="operator", step_id=node.step_id, ok=True, output=<"answered: <questionId>">,
  next_step=<route target>)`. This makes `route_counts` survive, because the resume builder
  derives counts from persisted `next_step`s. Read `_route_outcome` and the builder (about
  lines 861–883) and prove it with a resume test.
- **The Lead's message.** The Lead branch of `_hop_message` currently returns `instruction +
  description` only. Append `\n\n## Operator answers\n` plus one `Q: …\nA: …` block per answer,
  in order, capped at 4,000 characters with the existing truncation marker helper (find it in
  `core/context.py`).
- **The `pre_input` screen.** Call
  `core.policy.policy_eval_detail("lead", "pre_input", text, trusted=False)` for every string
  value in `content`. On a `block` action, raise `AnswerRejected(policy_id)` and write nothing.
- **The audit line.** `audit_log("task.answer", f"project={p} task={t} step={s} channel={c}
  actor={a} action={action}")`. The content is never in the audit line.
- **Expiry.** `sweep_expired_questions(now)` iterates pods like P34-6 does. Import nothing from
  `core/inbox.py` (that would be a cycle risk); enumerate through the same pod enumeration.

## P34-11 — events and delivery (Wave 67, Sonnet)

Branch `p34-11-notify`. Allowed:
- `core/notify.py` (new);
- `edges/adapters/channels/{__init__,webhook,command,console}.py` (new);
- `cli/_notify.py` (new) and one `notify` stub in `cli/__init__.py`;
- `cli/_channels.py` (the `test` subcommand);
- `serve.py::_run_sweeps` (one call after dispatch);
- `cli/_pod.py::_pod_dispatch` (one call at the end);
- `config.py` (`NOTIFY_STATE_FILE`, `CHANNELS_HEALTH_FILE`);
- tests `tests/unit/core/test_notify.py` (new), `tests/unit/edges/test_channel_webhook.py`
  (new);
- specs as in the card; `docs/commands.md`.

- **The snapshot** is `{item_key: version}`:
  - `item_key` = `task:<pod>:<id>` or `approval:<token>`;
  - `version` = the status plus the question id or token;
  - plus `{"expiring": [tokens already warned]}`.

  An event is emitted when an item key is new, or its version changed into a notifiable state.
- **Delivery** runs after the snapshot is computed. Save the snapshot **before** delivering, so
  a crash mid-delivery never re-emits. A failed delivery is recorded in health and not retried
  on the next flush. State this at-most-once choice in the spec.
- **Webhook signature.** A test vector: with secret `whsec_` + base64(`b"test-secret"`),
  id `msg_1`, ts `1700000000`, body `{"a":1}`, compute the expected value in the test with
  `hmac.new(b"test-secret", b"msg_1.1700000000." + body, "sha256")`, then base64 and prefix
  `v1,`. The header must equal it.
- **The command dialect** runs through `subprocess.run([...], input=json_bytes, timeout=10,
  check=False)` in `edges/`. Pass `config.argv` as a list (a YAML list, stored as a
  JSON-encoded string in `config` because `config` is `dict[str, str]`; decode it in the
  adapter). Never `shell=True`.
- **The foreground flush** in `_pod_dispatch` runs **after** P34-4's summary rendering and
  prints nothing unless a delivery failed (one `ui.warn` line).

## P34-12 — the intake (Wave 68, Sonnet)

Branch `p34-12-intake`. Allowed:
- `core/handoff.py`;
- `core/dispatch.py`: the Implementer branch of `_hop_message`, `_run_input_step`'s question
  builder, a new `_check_brief_resources`, and `enqueue_task`'s signature;
- `core/context.py`, only to add `brief` to the rendered artifact without shedding it (read
  `DROP_ORDER`);
- `core/archetypes.py::_LEAD_BODY`;
- `templates/recipes/intake/` (new);
- `docs/recipes.md` (regenerate);
- the parity tests (the new line);
- tests in `tests/integration/test_dispatch.py`, `tests/unit/core/test_handoff.py`;
- specs as in the card.

- **The brief block** is the **last** ```` ```json ```` fenced block in the reply. Parse it
  with `json.loads`, then `TaskBrief.model_validate`. Any failure means `None`, never a raise.
  The verdict marker is parsed by the existing verdict gate, unchanged.
- **The recipe instructions** (the Lead step's `instructions` in `pipeline.yaml`) must fit a
  16k-context local model. Keep them under 900 characters, show one minimal example brief, and
  say "end with exactly one line: READY, NEEDS-INPUT or REJECT".
- **Recipe docs.** Copy the README structure of `templates/recipes/spec-first/README.md`, then
  run `scripts/gen_recipe_docs.py` and commit the regenerated `docs/recipes.md`.
- **The `REJECT` route.** Map `on: {REJECT: fail}` to `failureKind: "rejected"`. The generic
  route-to-fail path sets no failure kind today: add the kind only when the matched label is
  `REJECT`, and put the mapping in one constant.

## P34-13 — answer surfaces (Wave 68, Sonnet)

Branch `p34-13-answer-surfaces`. Allowed:
- `cli/_pod.py` (`dispatch` table: `answer`; `delegate` gains `--brief`);
- `cli/_chat.py` (new) and one `chat` stub in `cli/__init__.py`;
- `serve.py` (`_handle_post_tasks`: the `/tasks/<id>/answer` sub-path and `brief` on create);
- `cli/_mcp.py` (`tool_task_answer`);
- tests in `tests/unit/cli/test_pod.py`, `tests/unit/cli/test_chat.py` (new), the serve
  integration test file, and the MCP tool tests;
- specs as in the card; `docs/commands.md`.

- **HTTP.** Read `_handle_post_tasks` (about line 976) and `_handle_post_approvals` (about line
  914) for the Bearer, body-size and error conventions. Map the errors: `AnswerRejected` → 422
  with the policy id; `ValueError` from `validate_answer` → 422 with the message; a task not in
  `waiting_input` → 409.
- **The actor.** For the CLI, use `getpass.getuser()`. For HTTP, use `"http"` unless the body
  names `actor`; the Bearer is the authority, and `actor` is only a label. For MCP, `"mcp"`.

## P34-14 — ntfy, desktop, email (Wave 68, Haiku)

Branch `p34-14-dialects`. Allowed: `edges/adapters/channels/{ntfy,desktop,email}.py` (new);
three entries in `edges/adapters/channels/__init__.py::sink_for`;
`tests/unit/edges/test_channel_dialects.py` (new); operator-loop §"Dialects".

Each sink is a function `deliver(spec, event, *, secret: str | None, timeout: float) ->
DeliveryResult`, with exactly the signature of `webhook.py`'s (P34-11). Open `webhook.py`
first and copy its shape.

1. **ntfy.** `url = spec.config.get("server", "https://ntfy.sh").rstrip("/") + "/" +
   spec.config["topic"]`. `title, body = core.notify.render_text(event)`. Build a
   `urllib.request.Request(url, data=body.encode(), method="POST", headers={"Title": title,
   "Priority": "high" if event.type.endswith(("input_required", "approval.requested")) else
   "default"})` and add `Authorization: Bearer <secret>` if a secret is set. Pass the timeout.
2. **desktop.** On `sys.platform == "darwin"`: `["osascript", "-e", f'display notification
   {json.dumps(body)} with title {json.dumps(title)}']`. Otherwise: `["notify-send", title,
   body]`. Use `shutil.which` first; if the binary is missing, return a result with `ok=False,
   error="notify-send not found"`, and never raise.
3. **email.** `smtplib.SMTP(host, int(port or 587), timeout=timeout)` → `starttls()` →
   `login(user, secret)` → `send_message(msg)`, where `msg` is an
   `email.message.EmailMessage` with `Subject = f"[docket] {title}"`, `From`, `To` and
   `set_content(body)`. Wrap the whole thing in `try/except Exception`, returning `ok=False`.
4. **Tests.** A local `http.server` for ntfy; a temp dir with an executable `notify-send`
   script that writes its argv to a file, prepended to `PATH` via `monkeypatch.setenv`; for
   email, `monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)`. **Canary:** build a `minimal` event
   from an approval whose action is `git push origin CANARY_7f3`, and assert `CANARY_7f3`
   appears in no request, argv or message.

## P34-15 — interruption forecast and pre-grants (Wave 69, Sonnet)

Branch `p34-15-forecast-pregrant`. Allowed:
- `core/interruptions.py` (new);
- `cli/_pod.py` (`dispatch` table: `explain`, `pregrant`; the `delegate` summary line);
- `serve.py` (`/tasks/<id>/pregrants`);
- `cli/_mcp.py` (`tool_task_pregrant`);
- `cli/_chat.py` (the suggested-command line);
- tests; specs as in the card; `docs/commands.md`.

Forbidden: `core/tools.py`, `core/approval.py` (use `create_pregrant` as P34-5 shipped it).

- **Effective policies.** Resolve them through the same loader `docket policies test --pod`
  uses (`rg -n "def .*policies" src/docket/cli/_policies.py`), so the forecast agrees with what
  fires.
- **High-risk classes** come from `core/security.py`'s classifier tables. Read them; do not
  copy the lists.
- **The pre-grant digest** uses the `bash` tool's argument key, `command` (see
  `core/tools.py`'s bash schema: `"required": ["command"]`), through
  `canonical_args_digest("bash", {"command": cmd})`.

## P34-16 — Telegram as a channel (Wave 69, Sonnet)

Branch `p34-16-telegram-channel`. Allowed:
- `core/telegram.py` (a `_ANSWER_RE`, the `/answer` handler, the usage text, the verb list);
- `edges/adapters/channels/telegram.py` (new), and one `sink_for` entry;
- `tests/integration/test_telegram_channel.py`;
- `telegram-integration.spec.md` (amend 7, 8 and the Non-goals; new section);
- `templates/channels/07-telegram.yaml`, only if its description must change.

- **The regex.** `_ANSWER_RE = re.compile(r"^/answer(?:@\w+)?\s+(\S+)\s+(.+)$", re.DOTALL)`.
  `/answer` with a missing argument replies with the usage text (requirement 5 style).
- **Authorisation** uses the same `_authorize` path as `/approve`. The pod is the bound
  agent's project; refuse a task id from another pod.
- **Bound chat ids** for the sink come from the fleet bindings: read how `docket wire` stores
  them. Send only to chats whose id is in the channel's `actors`.
- **`TestInboundOnly`.** Rename and rewrite it in the same commit. Keep its docstring's reason
  and update it: outbound now exists only through the channel.

## P34-17 — integrator

This card is not delegated. Checklist, in order:
1. Merge Wave 69.
2. Write the three seam tests.
3. Extend and re-run the scenario (deterministic, then live with
   `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`).
4. Record the numbers against the P34-1 baseline.
5. Evaluate the two measurable deferred triggers.
6. Write the docs (the card's list).
7. Rebuild the agent-lane prose tests from the new README, never carrying old assertions.
8. Add the CI line.
9. Bump each spec once and update `specs/README.md`.
10. Run the full gates and `metrics.py --check`.
11. Commit the rollup; archive the board with `scripts/maint/split_board.py archive`.
12. Update ROADMAP's status paragraph.
