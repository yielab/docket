# Harness Mode Contract Specification

**Version**: 1.7.1
**Status**: Implemented (`docket exec`). Contract 1.1
(P35-2 through P35-11, Phase 35, closed 2026-10-04) is opt-in and fully implemented -- see
"Contract 1.1" below.
**Last Updated**: 2026-10-08

## Purpose

This specification defines the versioned, non-interactive contract an outside caller pins
against to run one docket agent, in one caller-supplied workspace, to completion. The
contract is the wire shape (`HarnessEvent`/`HarnessResult`) plus the refusal and mapping rules
around it, and the `docket exec` command that produces it. See
[ADR 0001](../../docs/adr/0001-harness-mode.md) for the full design reasoning.

## Scope

This specification covers:

- The `HarnessEvent`/`HarnessResult` envelope shapes and their generated JSON Schema
- Contract versioning and fail-closed behavior for an unrecognized version
- The refusal conditions a caller must satisfy before a run starts
- The mapping from a driver outcome to a published result
- The exit-code convention this contract adds to `cli-interface.spec.md`
- `docket exec` syntax, options, and process behavior

It does **not** cover:

- Interactive approvals, pod/team execution, or provisioning a workspace -- see ADR 0001's
  "What harness mode is not" section

## Syntax

```
docket exec --workspace DIR (--task TEXT | --task-file PATH) --model PROVIDER/ID
            [--role implementer] [--timeout SECONDS] [--agent-id ID]
```

`exec` executes synchronously and streams the wire protocol below on stdout. stdout carries
**only** that output; every log/diagnostic line goes to stderr. Every option is a declared
Typer option; an unknown option exits 2 before the command body runs. A finished run's record is
read with `docket task show <run-id>`.

The wire syntax is newline-delimited JSON (NDJSON): zero or more `HarnessEvent` lines, in
ascending `seq` order starting at 0 (the first is always a synthesized `harness_start` event),
followed by exactly one `HarnessResult` line. Every line MUST be valid, self-contained JSON --
no line depends on another to parse.

```
{"v":"1.0.0","token":"run-ok-1","seq":0,"ts":"...","event":{...}}
{"v":"1.0.0","token":"run-ok-1","seq":1,"ts":"...","event":{...}}
{"v":"1.0.0","token":"run-ok-1","status":"ok","model":{...},"usage":{...},...}
```

## Arguments

| Argument | Rule |
|---|---|
| `--workspace DIR` | required; must be an existing directory the caller owns -- never provisioned by this command |
| `--task TEXT` | the message the agent's turn starts from; mutually exclusive with `--task-file` |
| `--task-file PATH` | reads the task message from *PATH*; mutually exclusive with `--task` |
| `--model PROVIDER/ID` | required; the model the caller asked for (`HarnessResult.model.requested`) |

Exactly one of `--task`/`--task-file` MUST be given. A missing `--workspace`/`--model`, or
both/neither of `--task`/`--task-file`, is refused (exit 2) before `preflight` runs -- the
contract's fields below then take the place of these arguments for wire validation purposes.

### `HarnessEvent`

| Field | Type | Rule |
|---|---|---|
| `v` | string | MUST equal `HARNESS_CONTRACT_VERSION` (`"1.0.0"`) exactly; any other value MUST fail validation |
| `token` | string | the run token this event belongs to |
| `seq` | integer | contiguous ascending sequence, starting at 0 |
| `ts` | string | envelope timestamp |
| `event` | object | the exact record `core.trace.trace_event` produced for this line; docket's existing trace vocabulary, not a second one. This is additive by design: an `llm_call` record (see `trace-store.spec.md`) appears on stdout exactly like any other event type, and `docs/contracts/harness-v1/schema.json` is unchanged because this field's schema is `additionalProperties: true`. An `llm_call` record's payload may itself carry the optional `inputMessages`/`outputMessages`/`systemInstructions`/`systemInstructionsSha256` keys `trace-store.spec.md`'s "Captured content" section defines; this is the same additive, `additionalProperties: true` field, so a run with no exporter above `minimal` streams byte-identical `llm_call` lines to before those keys existed |

### `HarnessResult`

| Field | Type | Rule |
|---|---|---|
| `v` | string | same rule as above |
| `token` | string | the run token (`""` for a `refused` result, since no run was created) |
| `status` | enum | one of `ok`, `failed`, `blocked`, `cancelled`, `refused` |
| `stop_reason` | string | the driver's `failure_kind`, or `""` when `status` is `ok` |
| `error` | string | the driver's error text, or `""` when `status` is `ok` |
| `blocked` | object or null | `{tool, call_id, denial_kind, policy_id, reason}`; non-null only when `status` is `blocked` |
| `model` | object | `{requested, served}` -- what was asked for versus what answered the last request |
| `usage` | object | `{input_tokens, output_tokens, cached_tokens, turns}` -- measured counts only |
| `cost_usd` | null | always `null`; docket never reports a fabricated dollar figure |
| `run_state` | string | the underlying run record's state at the time of this result |

## Options

| Option | Command | Default | Rule |
|---|---|---|---|
| `--role NAME` | `implementer` | MUST name a role whose archetype does not deny `write` (see `agent_meta_for` below) |
| `--timeout SECONDS` | `300` | the whole turn's wall-clock budget, passed straight through to the driver |
| `--agent-id ID` | a generated `harness-<hex>` id | the id registered in the caller's `DOCKET_HOME` for this run only |

`run` additionally fixes `ToolContext.approval_mode` to `"refuse"` for every tool call in the
turn (ADR 0001 decision 11) -- there is no flag to change this in v1.

## Output

The generated schema for both shapes above is committed at
`docs/contracts/harness-v1/schema.json`, produced by `scripts/harness_schema.py` from the
`core.harness` Pydantic models. A test regenerates it into memory and asserts byte equality
with the committed file, so a reshaped field fails CI rather than drifting silently. Each
model's own nested `$defs` are hoisted to one root `$defs` object at generation time, because
`model_json_schema()` writes refs as `#/$defs/X`, which resolve against the *document* root
rather than the `definitions.<Model>` object a naive merge would nest them under; a nested
placement is syntactically valid JSON but not a schema a standard validator can resolve.
Four hand-authored, line-validated example transcripts live at
`tests/fixtures/harness-contract/v1/{ok,blocked,cancelled,refused}.ndjson`, and a test validates
every line of every fixture against the committed file itself as JSON Schema (`#/definitions/
HarnessEvent` / `#/definitions/HarnessResult`), not only through the Pydantic models.

## Return

`docket exec` is the one named exception to `cli-interface.spec.md`'s flat 0/1
convention:

| Code | Meaning |
|---|---|
| 0 | the run's terminal `HarnessResult.status` is `ok` |
| 1 | the run reached a terminal, non-`ok` result (`failed`, `blocked`, or `cancelled`) |
| 2 | refused before any run started; exactly one `HarnessResult` with `status: refused` is printed |

## Validation

- **Version fail-closed.** A `HarnessEvent` or `HarnessResult` naming any `v` other than
  `HARNESS_CONTRACT_VERSION` MUST fail Pydantic validation. A fixture is not tolerated merely
  because its other fields are well-formed.
- **Refusal table.** `core.harness.preflight(environ, home_default, workspace)` MUST return a
  refusal when: `DOCKET_HOME` is unset; `DOCKET_HOME` resolves to the caller's default home;
  `DOCKET_LLM_BASE_URL` is unset; `DOCKET_NO_TRACE=1`; or `workspace` is not a directory. It
  MUST return `None` when every condition above is satisfied.
- **Result mapping.** `core.harness.result_from(turn, usage, run)` MUST map a successful
  `TurnResult` to `status: ok`; a `failure_kind` of `run_cancelled` to `status: cancelled`; an
  error naming `approval_unavailable` to `status: blocked` with the parsed rule; any other
  failure to `status: failed`. `model.served` MUST come from `turn.raw.get("model")`, never
  from what was requested.
- **Role usage error.** `core.harness.agent_meta_for(...)` MUST raise for a role whose
  `denied_tools` includes `write` -- harness mode's one job is to make an edit.
- **Schema pin.** `scripts/harness_schema.py`'s generated content MUST be byte-identical to
  the committed `docs/contracts/harness-v1/schema.json`.
- **Fixture validity.** Every line of every committed fixture MUST validate against
  `HarnessEvent` (all but the last line) or `HarnessResult` (the last line).
- **CLI argument checks precede `preflight`.** `docket exec` MUST refuse (exit 2, one
  `HarnessResult` with `status: refused`) a missing `--workspace`, a missing `--model`, or
  both/neither of `--task`/`--task-file`, before `core.harness.preflight` ever runs.
- **`approval_mode` reaches the driver.** `docket exec` MUST pass
  `DOCKET_APPROVAL_MODE=refuse` in `run_turn`'s `env`, and `DocketDriver.run_turn` MUST map it
  onto `ToolContext.approval_mode` -- an unset or unrecognized value MUST resolve to `"wait"`.
- **Isolation.** No `docket exec` invocation may read or write anything under the
  operator's own default `DOCKET_HOME` -- every docket-owned file it touches lives under the
  caller-supplied home.

## Contract 1.1

**Status of this section: implemented (Phase 35 closed 2026-10-04).** ADR 0017 (D-51) opened a
second, opt-in wire contract, `1.1.0`, alongside the unchanged `1.0.0` default. P35-2 shipped the
models, generated schema, fixtures, and the `--contract` flag that selects which version is stamped
on every line. P35-3 (Section 3), P35-5 (Section 5), P35-6 (Section 4), P35-9 (Section 6) and
P35-11 (`approvals`, Section 2 and Section 5) have landed live. P35-10 is the integrator card: a
consumer seam test drives the real subprocess against the committed schema, and the live run is
recorded in ADR 0017.
`task` is populated by recipe runs and stays `null` otherwise. Process lifecycle events ride the
`event` stream itself, independent of the result fields.

### 1. Selecting the contract

`docket exec` accepts a `--contract` option:

| Value | Effect |
|---|---|
| `1.0` (default) | Every line stamps `v: "1.0.0"`; behavior is byte-identical to before this option existed. |
| `1.1` | Every line -- events, and the terminal result, including a refusal reached after this flag parsed -- stamps `v: "1.1.0"` and validates against the v1.1 shapes below. |
| anything else | Refused (exit 2, one `HarnessResult` with `status: refused`), before `preflight` runs, like any other malformed argument. |

### 2. The v1.1 envelope

`HarnessEventV11` has the same fields as `HarnessEvent` (`token`, `seq`, `ts`, `event`), with
`v` pinned to `"1.1.0"` instead of `"1.0.0"`. `event` stays an open dict
(`additionalProperties: true`): a process lifecycle event type (`process_started`,
`process_exited` -- Section 3 below) needs no schema change to appear on the stream.

`HarnessResultV11` carries every `HarnessResult` field plus:

| Field | Type | Rule |
|---|---|---|
| `files` | array of `FileChange` | Which files the run touched (Section 4). `[]` when nothing was written. |
| `task` | `HarnessTask` or null | Recipe/task-run state. `null` unless the run is a recipe run (Section 6). |
| `limits` | `Limits` | Caller-declared ceilings echoed back. `{"maxTokens": null}` unless `--max-tokens` was given (Section 4). |
| `approvals` | array of `ApprovalEntry` | Every approval the run requested, in request order, each `{token, tool, callId, outcome}` (Section 5, "Approvals on the result"). `[]` when the run asked for none. |

`FileChange` is `{path: string, op: "write"|"edit"|"delete"|"unknown"}`.

`HarnessTask` is `{status: string, hops: array of object, evidence: object or null, brief:
object or null}`.

`Limits` is `{maxTokens: integer or null}`.

### 3. Process lifecycle events -- Implemented and live (P35-3)

`process_started`/`process_exited` event records appear on the `event` stream for a `bash` tool
call with no harness-specific code: `_run`'s `with _trace.subscribe(_emit):` already relays
every trace record verbatim, so the two event types `core/trace.py`'s `EVENT_TYPES` gained
(wired by `edges/adapters/docket_runtime.py::_build_on_process`, see
`specs/functional/trace-store.spec.md` "Process lifecycle events" for the owning contract)
reach this stream for free, under both `--contract 1.0` and `--contract 1.1` alike -- this
section only documents the shape a v1.1 consumer sees, it does not gate on the flag.

- `process_started`'s payload is exactly `{"pgid": <int>, "tool": "bash"}`.
- `process_exited`'s payload is `{"pgid": <int>, "tool": "bash", "exitCode": <int>}` on a real
  exit, or `{"pgid": <int>, "tool": "bash", "signal": "SIGKILL"}` when the tool handler killed
  the process group (a timeout or `docket task cancel` reaching it) -- never both keys, never
  neither.
- Exactly one `process_started`/`process_exited` pair appears per `bash` call; a turn with no
  `bash` call carries neither event, byte-identical to before this capability existed.

Verified live by `tests/integration/test_harness_cli.py::TestContract11Run::
test_a_bash_call_reports_process_lifecycle_events_on_the_v11_stream`, which spawns a real
`docket exec --contract 1.1` subprocess with a scripted `bash` tool call and asserts both
events appear on stdout in order with a real pgid.
`tests/fixtures/harness-contract/v1.1/cancelled-process.ndjson` is a hand-authored sample of the
signal-carrying shape (`docket task cancel` reaching a live `bash` subprocess is exercised by
`tests/integration/test_bash_cancellation.py`, not by the harness subprocess tests, since it
requires a `run` `cancel` call from a second thread rather than SIGTERM-ing the harness process
itself).

### 4. Written paths, token file, and caller limits -- Implemented and live (P35-6)

1. **Files.** Every run under `--contract 1.1` reports `HarnessResultV11.files`, with no flag.
   - The run's own `write` and `edit` calls come from the harness's trace subscription. A call
     counts once its `tool_result` reports `executed` and `ok`, so a call a policy blocked or
     that failed is not listed. Op is `write` or `edit`.
   - In a git workspace, `git status --porcelain -z --untracked-files=all` over the workspace's
     repository adds every changed path, so a file a `bash` call created appears. Untracked or
     added paths are `write`, deleted paths `delete`, and any other change `unknown`. A path
     already named by a `write`/`edit` call keeps that call's op. A non-git workspace reports
     only the calls.
   - `files` means what this run changed, not what was merely dirty or produced around it. The
     harness fingerprints `git status` (status code, size, `mtime_ns`) before the turn or recipe
     starts, and a git-reported path whose fingerprint is unchanged at the end is dropped. In a
     recipe run, a path a hop's verify command created or changed (found by fingerprinting
     before and after the command, recorded as internal `touched` on that hop's verify evidence,
     never published) is dropped too. Neither rule drops a path the run's own `write`/`edit`
     call touched, and a file a `bash` call created during the turn is still listed.
   - Paths are POSIX and relative to the workspace, outside paths are dropped, and each path
     appears once. Diff content is never reported.
2. **`--token-file PATH`.** Written atomically (staged, then renamed) with mode `0600` after the
   run is created and before the first model request. Content is one JSON object:
   `{"v": "1.1.0", "token": "<run token>", "pid": <harness pid>}`. The parent directory must
   exist, or the run is refused with exit 2.
3. **The stderr line.** The line
   `docket exec: run <token> agent=<id> model=<model> role=<role>` is the pinned stable
   format, written to stderr once the run exists and after the token file. A caller matches it
   with `^docket exec: run (\S+) agent=(\S+) `. Stdout stays NDJSON only.
4. **`--max-tokens N`** (a positive integer). The turn's measured-token bound: the harness sets
   the `DOCKET_TURN_TOKEN_BUDGET` key of `run_turn`'s env, which the driver pops into
   `LoopConfig.token_budget` in place of `AGENT_LOOP_TOKEN_BUDGET`. Exceeding it stops the turn
   (`status` `failed`, `error` `exceeded token_budget=N (used M)`). `limits.maxTokens` echoes N;
   without the flag it stays `null`. The bound is measured usage, not a dollar figure.
5. **`--policy FILE`** (repeatable). Each file is checked with `core.policy.validate_policy`
   before any run record is created. If any file is invalid, the harness exits 2 with one
   `refused` result that names the problem, and nothing is created or copied. Valid files are
   copied into the policies directory (`$POLICIES_DIR`, which defaults to `$DOCKET_HOME/policies`)
   and are active for the turn. Two `--policy` files with the same basename are refused.
6. **Flags need `--contract 1.1`.** `--token-file`, `--max-tokens` and `--policy` under
   `--contract 1.0`, or with no `--contract`, exit 2 with a refused result stamped `1.0.0`, the
   same way `--answers` does. `--max-tokens` must be a positive integer.

Verified by `tests/integration/test_harness_cli.py::TestWrittenPathsAndLimits` (a write and an
edit both listed; an untracked file written by `bash` in a git workspace; the token file's mode
and content read inside the fake endpoint's first request; `--max-tokens` stopping the turn; a
`--policy` that blocks `bash`; a malformed policy refused before any run; the flag and value
refusals), and by the `files`-related tests in `tests/unit/core/test_harness.py`.
`tests/fixtures/harness-contract/v1.1/ok-files.ndjson` is a hand-authored sample of the shape.

### 5. Answers on stdin -- Implemented and live (P35-5)

With `--answers stdin` a caller resolves a paused approval by writing one `AnswerLine` per line
(`{v, token, answer: {approvalToken, action: "accept"|"decline"|"cancel", content?}}`, the MCP
elicitation result shape) to this process's stdin, while the run is live. The reader is
`src/docket/cli/_harness_answers.py`; the approval rules it applies are owned by
`specs/functional/security-gates.spec.md`, "The harness answer channel".

1. **Flags.** `--answers stdin` and `--answer-timeout S` (a positive integer). Either one under
   `--contract 1.0` (the default) exits 2 with a refused result. `--answer-timeout` without
   `--answers stdin` exits 2. `--answers` with any other value exits 2. `--answers stdin` with
   `--task-file` naming stdin (`-`, `/dev/stdin` or `/proc/self/fd/0`) exits 2 with a reason that
   contains "conflicts".
2. **Mode.** Under `--answers stdin` the run's approval mode is `wait`, so an approval-gated call
   blocks until answered; otherwise the mode stays `refuse`, unchanged. The wait bound is
   `--answer-timeout` when given, else `TOOL_APPROVAL_TIMEOUT`. The harness is its own process, so
   it sets that config attribute for the run and restores it afterwards.
3. **Reading.** One `AnswerLine` per stdin line. A line that does not validate, or that names a
   different run's token, is ignored with one stderr line that never echoes the line's contents.
   A `questionId` answer is routed to a recipe run's open question (Section 6); outside a recipe
   run it is ignored with a stderr line.
4. **Timeout.** An approval with no answer by its deadline is denied (`approval_timeout`). The
   refusal is an ordinary tool result: the model sees it, and the run ends by its turn's own
   outcome, so exit 0 is possible with status `ok`.
5. **Event.** The `approval_requested` event carries `tool` and `callId` of the call it pauses on.
   A caller matches its answer on `token` (the run) and `payload.token` (the approval).
6. **Stdout.** Stdout stays NDJSON only. Every answer diagnostic goes to stderr.
7. **Approvals on the result (P35-11).** `HarnessResultV11.approvals` lists every approval the run
   requested, from the run's own `approval_requested` trace events. `outcome` is `accepted` or
   `declined` for an answer line this process applied; `timed_out` when the wait bound denied it
   with no answer (fail closed); `unanswered` when the run ended with it still pending, or was
   cancelled while it waited. `refused_content` is reserved: a content line held by a `pre_input`
   policy leaves the approval pending, so its final outcome is the later answer or `timed_out`. The
   `status` and exit code do not change. A denied or timed-out approval still ends the run by its
   turn's own outcome, so `approvals` is the field a caller reads to tell that apart from a clean run.

8. **Option ids (P36-6, contract 1.1 answers).** An approval answer's `content.optionId` may be
   `approve_once` or `approve_task` (with `accept`) or `deny` (with `decline`; `content.reason`
   is the reason). `approve_task` grants and also pre-grants one identical call for the rest of the
   run (security-gates In-turn requirement 8); the run is one agent turn, so "task" here means
   that turn. In pod dispatch the same option lasts for the pod task (operator-loop 5a). `accept` with no `optionId` means `approve_once`.
   An unknown `optionId`, or one that contradicts the action, is ignored with one stderr line and
   the approval stays pending. Under contract 1.1 `approval_requested` carries `rationale` and
   `options`; under 1.0 they are omitted, so the 1.0 stream is unchanged.
9. **Consult questions (P36-7, contract 1.1).** The question's `taskId` is the run token. A `consult` tool call (operator-loop spec,
   "Consult") under `--answers stdin` emits a `question_asked` event whose payload is
   `{questionId, kind, mode, question}`, `question` being the `QuestionV11` on the wire. A
   `questionId` line whose id is that waiting call's is routed to it, not to a recipe run's open
   question: its `content` is screened by `pre_input` like an approval's (a held line leaves the
   call waiting), then validated with `validate_answer_v11` (`content.optionId` names the chosen
   option; an invalid line is ignored with one stderr line and the call keeps waiting). The
   tool result is `{action, optionId, content}`. A `questionId` that matches no waiting call
   keeps its earlier route (a recipe run's question, else ignored with "need --recipe"). With no
   answer by `--answer-timeout` (or at end of stdin) the call returns "no answer; decide
   yourself". Without `--answers stdin` (mode `refuse`) the call ends the turn `blocked`, as an
   unanswerable approval does, and the 1.1 result carries the typed `question` field (the
   `QuestionV11`); `question` is `null` otherwise and absent from 1.0. Pod-dispatch park and
   re-entry of a consultation arrive with P36-8.

Verified by `tests/integration/test_harness_cli.py::TestAnswersOnStdin` (granted, declined,
timed out, a malformed or foreign line that is never echoed, a content line held by a
`pre_input` policy, a question answer, and the usage refusals), which drive a real
`docket exec --answers stdin` subprocess over pipes, and by
`tests/unit/cli/test__harness_answers.py`. `tests/fixtures/harness-contract/v1.1/asked-answered.ndjson`
and `answer-lines.ndjson` remain hand-authored samples of the shape.

### 6. Recipe runs -- Implemented and live (P35-9)

`docket exec --contract 1.1 --recipe NAME|DIR --task ...` runs one recipe, in place, for one
task, and reports its hops through `HarnessResultV11.task`.

1. **Arguments.** `--recipe` takes a name or directory that `docket pod recipes` resolves. It is
   mutually exclusive with `--role` (exit 2), needs `--contract 1.1` (exit 2 under 1.0), and
   refuses `--max-tokens` and `--agent-id` (exit 2): a recipe run's turns are dispatched by the
   pod, so the single-agent turn bound and id do not reach them. `--verify CMD` (valid only with
   `--recipe`) sets the Implementer's verify command, validated as `docket pod add --verify` is. An
   unknown recipe is refused (exit 2) before any pod exists. `--task`/`--task-file`, `--model`,
   `--timeout`, `--token-file`, `--policy`, `--answers` and `--answer-timeout` keep their meaning.
2. **Execution.** `core.harness_pipeline.run_recipe_task` provisions one ephemeral in-place pod on
   the workspace, applies the recipe, pins every member to `--model`, and dispatches the task.
   `requireVerify` is always true on that pod, so an Implementer hop with no verify command fails
   with `verifyCmd required but not set`.
3. **Approval mode (decision).** The run's approval mode is the ephemeral pod's Lead `approvalMode`
   setting, written through the typed `PodSettings` writer and read by dispatch on every hop: `wait`
   under `--answers stdin`, else `refuse`. `run_recipe_task` therefore takes no `env` argument. The
   mode is a pod setting, not a driver env key, so each hop of the recipe reads the same value and
   no second channel exists.
4. **Result.** `task` is `{status, hops, brief}`. `status` is the task record's own status. `task.evidence` is
   the task's evidence-v1 document (`core.evidence.task_evidence(project, task_id)` dumped by
   alias), the same one `docket task show <task> --json` and `GET
   /tasks/<p>/<id>/evidence` serve, and `null` when no task record exists. Each
   hop is `{role, stepId, ok, verdict, verify, evidence}`, in order, read from the task record
   after the last dispatch. `brief` is the Lead's typed intake brief when one parsed, else `null`.
   `files` is collected as in Section 4. `usage` sums the measured counts of every pod member.
   `model.served` is `""`, since a recipe run has no single turn to read it from.
5. **Status.** A task `done` maps to `ok` (exit 0). A `failed` task maps to `failed`. A hop error
   naming `approval_unavailable` maps to `blocked`, with `blocked` parsed as in Section 4's v1
   mapping. A task left `waiting_input` or `waiting_approval` maps to `blocked`. A `cancelled`
   task maps to `cancelled`. Every non-`ok` exit is 1.
6. **Answers.** Under `--answers stdin`, a `questionId` line whose id is the open question's id is
   applied with `core.answers.answer_task` (channel `harness`), and the task is dispatched again
   from its own route. A line for another question is ignored with a stderr line. End of stdin, or
   `--answer-timeout` elapsing with no answer, leaves the task parked, which maps to `blocked`.
   Without `--answers stdin` no question can be answered, so a parked task is `blocked`.
7. **Stream.** Trace events from every pod member stream as ordinary `event` lines, the same relay
   a single-agent run uses.

Verified by `tests/integration/test_harness_cli.py::TestRecipeRun` (the `tdd` hops and the
`check-red` command step; a failing verify with its `exitCode`; the `intake` question answered on
stdin and reaching the Lead's re-entry; an unanswered question ending `blocked`; a refused
approval ending `blocked` with its rule; the usage refusals), and by
`tests/integration/test_harness_pipeline.py` (`TestRequireVerify`, `TestResumeAfterQuestion`).
`tests/fixtures/harness-contract/v1.1/recipe-ok.ndjson` remains a hand-authored sample of the
shape.

### 7. Output

The generated schema for the three v1.1 shapes (`HarnessEvent`, `HarnessResult`, `AnswerLine`)
is committed at `docs/contracts/harness-v1.1/schema.json`, produced by the same
`scripts/harness_schema.py` script (`render_v11()`), with the same `$defs`-hoisting rule as
v1's `render()`. A test regenerates it into memory and asserts byte equality with the committed
file. `tests/integration/test_harness_v11_consumer.py` (P35-10) drives the real `--contract 1.1`
subprocess, reads `process_started`/`process_exited`, answers an approval on stdin, reads `files`
and a `--recipe` `task` block, and validates every emitted line against that committed file. Five hand-authored, line-validated example transcripts live at
`tests/fixtures/harness-contract/v1.1/{ok-files,asked-answered,cancelled-process,recipe-ok,
answer-lines}.ndjson`; the first four end on a `HarnessResultV11` line like the v1 fixtures,
and `answer-lines.ndjson` holds only `AnswerLine` lines (a stdin sample, not a stdout
transcript). A test validates every line of every result-ending fixture against the committed
v1.1 file itself as JSON Schema, not only through the Pydantic models.

### 8. Validation

- **v1.1 version fail-closed.** A `HarnessEventV11`, `HarnessResultV11`, or `AnswerLine` naming
  any `v` other than `"1.1.0"` MUST fail validation -- including `"1.0.0"`, since the two
  envelopes are validated independently and neither tolerates the other's version string.
- **`Answer` arity.** Exactly one of `approvalToken`/`questionId` MUST be set; both set or
  neither set MUST fail validation.
- **`--contract` fail-closed.** A value other than `1.0`/`1.1` MUST be refused (exit 2) before
  `preflight` runs, like any other malformed argument, with no partial output.
- **Refusal stamps the selected contract.** Once `--contract` itself parses successfully, every
  refusal reached afterward (a later usage error, a `preflight` refusal, an `agent_meta_for`
  usage error) MUST stamp the version that was selected, not the default.
- **Behavior beyond the stamp.** Under `--contract 1.1`, `files` is populated (Section 4) and
  process lifecycle events ride the stream (Section 3). `task` is populated by a recipe run
  (Section 6) and `null` otherwise, and `limits` changes only with `--max-tokens` (Section 4).

## Changelog

### Version 1.7.1 (2026-10-08)

- Command names follow ADR 0022.

### Version 1.7.0 (2026-10-07)

- The command is `docket exec`; the wire contract, refusal table and exit codes 0/1/2 are unchanged. `docket harness status` is removed; a run's record is read with `docket task show <run-id>`. Options are declared Typer options.

### Version 1.6.0 (2026-10-05)

Waves 89-90 close (W89-10): the entries below were Unreleased and are now this version.

- Requirement 8 wording: `approve_task` under the harness lasts the single run; the pod-task meaning is operator-loop 5a.
- A harness consult's `question.taskId` is the run token (`ToolContext.task_id`, set through `DOCKET_TASK_ID`), not the session key (Section 5 item 9).

### Version 1.5.0 (2026-10-04)

Phase 36 close (P36-10): the entries below were Unreleased and are now this version.

- **P36-4.** **`task.evidence` is evidence-v1.** Section 6 item 4. The schema already types it as
  `object or null`, so no schema change and
- **P36-7.** **Consult questions.** Section 5 item 9: `question_asked` events, `questionId` routing to a
  waiting `consult` call, and `HarnessResultV11.question` on a blocked consultation (schema
  regenerated; additive and optional).
- **P36-6.** **Option ids on approval answers.** Section 5 item 8. `approval_requested` gains `rationale`
  and `options` under 1.1 only. No schema change (`content` is free-form),
- **P35-12.** **`files` excludes baseline-dirty and verify-produced paths.** Section 4 now states the
  baseline snapshot and the verify-artifact exclusion. No schema change,

### Version 1.4.0 (2026-10-04)

- **Contract 1.1 complete (Phase 35 close, P35-10).** Every Contract 1.1 section is now
  implemented and live. The version bump for the three cards below, which left it to the
  integrator, is this one. The v1.0 shapes are unchanged.
  - **Written paths, token file, caller limits (P35-6).** Section 4: `files`, `--token-file`,
    `--max-tokens`, `--policy` under `--contract 1.1`.
  - **Recipe runs (P35-9).** Section 6: `--recipe NAME|DIR` with `--verify`, `task` block,
    `questionId` answers. Decisions: the approval mode travels as the ephemeral pod's Lead
    `approvalMode` setting, so `run_recipe_task` takes no `env` parameter; `--verify` is added
    because `requireVerify` without a verify command fails every hop; `--max-tokens` and
    `--agent-id` are refused with `--recipe`.
  - **Approvals on the result (P35-11).** Section 2 and Section 5 item 7: `approvals` lists each
    approval with `accepted`, `declined`, `timed_out` or `unanswered`. This closes Wave 72
    caveat 2: the status and exit code are unchanged, so a caller reads `approvals` to tell a
    denied approval from a clean run.
  - **Integrator (P35-10).** The consumer seam test, the schema-validated live run recorded in
    ADR 0017, and a section 7 sentence naming the seam test.
- **Deferred to the next phase, not in this contract.** A process-wide `TOOL_APPROVAL_TIMEOUT`
  bound for the run (Wave 72 caveat 3; the per-run env route needed edits outside the owning
  card's list), and the answer reader's daemon thread for `--answers stdin`, which is not joined
  and blocks in `sys.stdin` (`cli/_harness_answers.py::serve`; TODO.md, Phase 35 close).

### Version 1.3.0 (2026-10-03)

- **Answers on stdin (P35-5, ADR 0017).** Section 5 is implemented and live: `--answers stdin`
  and `--answer-timeout S` under `--contract 1.1`, one MCP-shaped `AnswerLine` per stdin line.
  The approval rules are in `security-gates.spec.md`, "The harness answer channel". The default
  `--contract 1.0` wire is unchanged.

### Version 1.2.0 (2026-09-29)

- **Contract 1.1 opens (P35-2), process events land live (P35-3).** New "Contract 1.1" section:
  a second, opt-in wire contract (`--contract 1.0|1.1`, default `1.0`, byte-identical) with
  `HarnessEventV11`/`HarnessResultV11`/`FileChange`/`AnswerLine`/`HarnessTask`/`Limits`, a
  published `docs/contracts/harness-v1.1/schema.json`, and five hand-authored v1.1 fixtures.
  Process lifecycle events (Section 3) reach the stream with no harness-specific code, since
  `_run`'s existing `with _trace.subscribe(_emit):` relays every trace record verbatim. Written
  paths/limits, stdin answers, and recipe runs (Sections 4-6) remain planned, each owned by a
  separate later card.

### Version 1.1.3 (2026-09-28)

- **Event row note (P33-3).** An `llm_call` record on the event stream may carry the
  captured-content keys when an enabled exporter asks for them; the schema is unchanged
  (`additionalProperties: true`).

### Version 1.1.2 (2026-09-27)

- P32-1 adds the `llm_call` trace event (`trace-store.spec.md`, `agent-loop.spec.md` 1.25.0). No
  wire change: the `event` field's table row now says so explicitly, and the committed schema is
  unchanged (`additionalProperties: true`) -- an `llm_call` line streams on stdout like any other
  event type. Contract version (`HARNESS_CONTRACT_VERSION`) stays `1.0.0`.

### Version 1.1.1 (2026-09-25)

- The committed schema hoists nested `$defs` to the document root so it validates under a standard Draft 2020-12 validator; every fixture is validated against the file (W37-C4). Contract version unchanged.

### Version 1.1.0 (2026-09-12)

- W30-C4 ships `docket harness run`/`docket harness status`: the sequence in ADR 0001 wired
  end to end (preflight, meta registration, a run record, a synthesized `harness_start` event,
  the trace-subscriber stream, `SIGTERM`-driven cancellation, `result_from`). `HARNESS_CONTRACT_VERSION`
  stays `1.0.0` -- the wire shape is unchanged; this version bump is the spec document's own,
  covering the now-implemented Syntax/Arguments/Options/Return sections.
- `DOCKET_APPROVAL_MODE` added beside `PIPELINE_WORKTREE_ENV` in `core/runtime_driver.py`: the
  same internal env-coordinate route, now the way a non-interactive caller reaches
  `ToolContext.approval_mode="refuse"` in production.

### Version 1.0.0 (2026-09-12)

- W30-C3 defines the harness-mode contract: `core.harness`'s models and pure functions, the
  generated and pinned JSON Schema, four hand-authored NDJSON fixtures, and the trace
  subscriber seam the future command streams through. No command exists yet -- see Status.
