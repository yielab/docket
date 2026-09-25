# Harness Mode Contract Specification

**Version**: 1.1.1
**Status**: Implemented (`docket harness run`/`docket harness status`, W30-C4)
**Last Updated**: 2026-09-25

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
| `event` | object | the exact record `core.trace.trace_event` produced for this line; docket's existing trace vocabulary, not a second one |

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

## Changelog

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
