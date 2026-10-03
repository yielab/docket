# Harness Mode Contract Specification

**Version**: 1.3.0
**Status**: Implemented (`docket harness run`/`docket harness status`, W30-C4). Contract 1.1
(P35-2, P35-3, P35-5) is opt-in and partially implemented -- see "Contract 1.1" below.
**Last Updated**: 2026-10-03

## Purpose

This specification defines the versioned, non-interactive contract an outside caller pins
against to run one docket agent, in one caller-supplied workspace, to completion. The
contract is the wire shape (`HarnessEvent`/`HarnessResult`) plus the refusal and mapping rules
around it, and the `docket harness run`/`docket harness status` command that produces it. See
[ADR 0001](../../docs/adr/0001-harness-mode.md) for the full design reasoning.

## Scope

This specification covers:

- The `HarnessEvent`/`HarnessResult` envelope shapes and their generated JSON Schema
- Contract versioning and fail-closed behavior for an unrecognized version
- The refusal conditions a caller must satisfy before a run starts
- The mapping from a driver outcome to a published result
- The exit-code convention this contract adds to `cli-interface.spec.md`
- `docket harness run`/`docket harness status` syntax, options, and process behavior

It does **not** cover:

- `docket harness status`'s reconstructed-result CLI output shape (best-effort, not
  wire-pinned -- only the `run` NDJSON/result stream and the exit-code table are a published
  contract an external caller pins against)
- Interactive approvals, pod/team execution, or provisioning a workspace -- see ADR 0001's
  "What harness mode is not" section

## Syntax

```
docket harness run --workspace DIR (--task TEXT | --task-file PATH) --model PROVIDER/ID
                    [--role implementer] [--timeout SECONDS] [--agent-id ID]
docket harness status TOKEN
```

`run` executes synchronously and streams the wire protocol below on stdout; `status` prints
one JSON line reporting a prior run token's liveness. stdout carries **only** that output;
every log/diagnostic line goes to stderr.

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

| Argument | Command | Rule |
|---|---|---|
| `--workspace DIR` | `run` | required; must be an existing directory the caller owns -- never provisioned by this command |
| `--task TEXT` | `run` | the message the agent's turn starts from; mutually exclusive with `--task-file` |
| `--task-file PATH` | `run` | reads the task message from *PATH*; mutually exclusive with `--task` |
| `--model PROVIDER/ID` | `run` | required; the model the caller asked for (`HarnessResult.model.requested`) |
| `TOKEN` | `status` | a run id printed as the `token` field of a prior `run` invocation |

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
| `--role NAME` | `run` | `implementer` | MUST name a role whose archetype does not deny `write` (see `agent_meta_for` below) |
| `--timeout SECONDS` | `run` | `300` | the whole turn's wall-clock budget, passed straight through to the driver |
| `--agent-id ID` | `run` | a generated `harness-<hex>` id | the id registered in the caller's `DOCKET_HOME` for this run only |

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

`docket harness run` is the one named exception to `cli-interface.spec.md`'s flat 0/1
convention:

| Code | Meaning |
|---|---|
| 0 | the run's terminal `HarnessResult.status` is `ok` |
| 1 | the run reached a terminal, non-`ok` result (`failed`, `blocked`, or `cancelled`) |
| 2 | refused before any run started; exactly one `HarnessResult` with `status: refused` is printed |

`docket harness status` always returns 0 on a successful lookup (whatever `state`/`result` it
reports) and 1 only on a usage error (a missing `TOKEN` argument).

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
- **CLI argument checks precede `preflight`.** `docket harness run` MUST refuse (exit 2, one
  `HarnessResult` with `status: refused`) a missing `--workspace`, a missing `--model`, or
  both/neither of `--task`/`--task-file`, before `core.harness.preflight` ever runs.
- **`approval_mode` reaches the driver.** `docket harness run` MUST pass
  `DOCKET_APPROVAL_MODE=refuse` in `run_turn`'s `env`, and `DocketDriver.run_turn` MUST map it
  onto `ToolContext.approval_mode` -- an unset or unrecognized value MUST resolve to `"wait"`.
- **Isolation.** No `docket harness` invocation may read or write anything under the
  operator's own default `DOCKET_HOME` -- every docket-owned file it touches lives under the
  caller-supplied home.

## Contract 1.1

**Status of this section: partially implemented.** ADR 0017 (D-51) opens a second, opt-in wire
contract, `1.1.0`, alongside the unchanged `1.0.0` default. P35-2 ships the models, generated
schema, fixtures, and the `--contract` flag that selects which version is stamped on every line.
P35-3 (Section 3) has since landed live. Three behaviors remain planned (Sections 4-6 below).
Passing `--contract 1.1` today yields a v1.1-shaped stream whose `files`/`task`/`limits` fields
are still always empty/default, because nothing yet populates them -- process lifecycle events
ride the `event` stream itself, independent of those three fields.

### 1. Selecting the contract

`docket harness run` accepts a `--contract` option:

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
| `files` | array of `FileChange` | Which files the run touched. `[]` until P35-6 populates it (Section 4). |
| `task` | `HarnessTask` or null | Recipe/task-run state. `null` until P35-9 populates it (Section 5). |
| `limits` | `Limits` | Caller-declared ceilings echoed back. `{"maxTokens": null}` until P35-6 enforces one (Section 4). |

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
  the process group (a timeout or `docket runs cancel` reaching it) -- never both keys, never
  neither.
- Exactly one `process_started`/`process_exited` pair appears per `bash` call; a turn with no
  `bash` call carries neither event, byte-identical to before this capability existed.

Verified live by `tests/integration/test_harness_cli.py::TestContract11Run::
test_a_bash_call_reports_process_lifecycle_events_on_the_v11_stream`, which spawns a real
`docket harness run --contract 1.1` subprocess with a scripted `bash` tool call and asserts both
events appear on stdout in order with a real pgid.
`tests/fixtures/harness-contract/v1.1/cancelled-process.ndjson` is a hand-authored sample of the
signal-carrying shape (`docket runs cancel` reaching a live `bash` subprocess is exercised by
`tests/integration/test_bash_cancellation.py`, not by the harness subprocess tests, since it
requires a `run` `cancel` call from a second thread rather than SIGTERM-ing the harness process
itself).

### 4. Written paths, token file, and caller limits -- Planned, owned by P35-6

Status: **Planned -- owned by P35-6.** Populating `HarnessResultV11.files` from what a turn
actually wrote/edited/deleted; a `--token-file` option; and a caller-declared `--max-tokens`
surfaced back through `limits.maxTokens` and enforced as a stop condition. This section is a
placeholder until that card lands; `tests/fixtures/harness-contract/v1.1/ok-files.ndjson` is a
hand-authored sample of the shape.

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
   A `questionId` answer is ignored with a stderr line until recipe runs (Section 6) exist.
4. **Timeout.** An approval with no answer by its deadline is denied (`approval_timeout`). The
   refusal is an ordinary tool result: the model sees it, and the run ends by its turn's own
   outcome, so exit 0 is possible with status `ok`.
5. **Event.** The `approval_requested` event carries `tool` and `callId` of the call it pauses on.
   A caller matches its answer on `token` (the run) and `payload.token` (the approval).
6. **Stdout.** Stdout stays NDJSON only. Every answer diagnostic goes to stderr.

Verified by `tests/integration/test_harness_cli.py::TestAnswersOnStdin` (granted, declined,
timed out, a malformed or foreign line that is never echoed, a content line held by a
`pre_input` policy, a question answer, and the usage refusals), which drive a real
`docket harness run --answers stdin` subprocess over pipes, and by
`tests/unit/cli/test__harness_answers.py`. `tests/fixtures/harness-contract/v1.1/asked-answered.ndjson`
and `answer-lines.ndjson` remain hand-authored samples of the shape.

### 6. Recipe runs -- Planned, owned by P35-9

Status: **Planned -- owned by P35-9.** `docket harness run --recipe NAME` executing a shipped
recipe in place and reporting its progress through `HarnessResultV11.task`. This section is a
placeholder until that card lands; `tests/fixtures/harness-contract/v1.1/recipe-ok.ndjson` is a
hand-authored sample of the shape.

### 7. Output

The generated schema for the three v1.1 shapes (`HarnessEvent`, `HarnessResult`, `AnswerLine`)
is committed at `docs/contracts/harness-v1.1/schema.json`, produced by the same
`scripts/harness_schema.py` script (`render_v11()`), with the same `$defs`-hoisting rule as
v1's `render()`. A test regenerates it into memory and asserts byte equality with the committed
file. Five hand-authored, line-validated example transcripts live at
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
- **No behavior change beyond the stamp.** `--contract 1.1` alone does not populate `files`,
  `task`, or enforce `limits` -- those are Sections 3-6 above, each owned by a later card.

## Changelog

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
