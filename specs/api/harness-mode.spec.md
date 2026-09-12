# Harness Mode Contract Specification

**Version**: 1.0.0
**Status**: Contract defined and test-pinned; `docket harness` ships in W30-C4
**Last Updated**: 2026-09-12

## Purpose

This specification defines the versioned, non-interactive contract an outside caller pins
against to run one docket agent, in one caller-supplied workspace, to completion. The
contract is the wire shape (`HarnessEvent`/`HarnessResult`) plus the refusal and mapping rules
around it -- not, yet, an implemented command. See
[ADR 0001](../../docs/adr/0001-harness-mode.md) for the full design reasoning.

## Scope

This specification covers:
- The `HarnessEvent`/`HarnessResult` envelope shapes and their generated JSON Schema
- Contract versioning and fail-closed behavior for an unrecognized version
- The refusal conditions a caller must satisfy before a run starts
- The mapping from a driver outcome to a published result
- The exit-code convention this contract adds to `cli-interface.spec.md`

It does **not** yet cover, because no command exists:
- `docket harness run`/`docket harness status` syntax, options, or CLI output
- Cancellation delivery, approval-mode wiring, or any process/signal behavior

## Syntax

There is no CLI syntax yet. The wire syntax is newline-delimited JSON (NDJSON): zero or more
`HarnessEvent` lines, in ascending `seq` order starting at 0, followed by exactly one
`HarnessResult` line. Every line MUST be valid, self-contained JSON -- no line depends on
another to parse.

```
{"v":"1.0.0","token":"run-ok-1","seq":0,"ts":"...","event":{...}}
{"v":"1.0.0","token":"run-ok-1","seq":1,"ts":"...","event":{...}}
{"v":"1.0.0","token":"run-ok-1","status":"ok","model":{...},"usage":{...},...}
```

## Arguments

Not applicable: no command exists yet. The contract's fields (below) take the place of
arguments for validation purposes.

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

Not applicable: no command exists yet.

## Output

The generated schema for both shapes above is committed at
`docs/contracts/harness-v1/schema.json`, produced by `scripts/harness_schema.py` from the
`core.harness` Pydantic models. A test regenerates it into memory and asserts byte equality
with the committed file, so a reshaped field fails CI rather than drifting silently. Four
hand-authored, line-validated example transcripts live at
`tests/fixtures/harness-contract/v1/{ok,blocked,cancelled,refused}.ndjson`.

## Return

`docket harness` (once shipped) is the one named exception to `cli-interface.spec.md`'s flat
0/1 convention:

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

## Changelog

### Version 1.0.0 (2026-09-12)

- W30-C3 defines the harness-mode contract: `core.harness`'s models and pure functions, the
  generated and pinned JSON Schema, four hand-authored NDJSON fixtures, and the trace
  subscriber seam the future command streams through. No command exists yet -- see Status.
