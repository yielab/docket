# Harness mode v1 — consumer packet

For the external plan-of-record that asked for a versioned non-interactive contract before
building against docket. Everything below resolves in this repository at tag `v0.2.0-beta.3`, the
first published release that ships harness mode.

## What to pin

| Fact | Value |
|---|---|
| Contract version | `1.0.0` (`HARNESS_CONTRACT_VERSION` in `src/docket/core/harness.py`) |
| JSON schema | `docs/contracts/harness-v1/schema.json` |
| Schema SHA-256 | `6dec6f8219482afe522efed5096acb008ab76ae9af668cc322fd645b14bb4771` |
| Fixtures | `tests/fixtures/harness-contract/v1/{ok,blocked,cancelled,refused}.ndjson` |
| Spec | `specs/api/harness-mode.spec.md` v1.1.0 |
| Shipped in | Phase 24 / Wave 30, cards W30-C1 through W30-C5 |
| First release | `v0.2.0-beta.3` (2026-09-18) |

The schema is generated from the Pydantic models by `scripts/harness_schema.py` and a test
regenerates it in memory and compares byte for byte, so the committed artifact cannot drift from
the code. A payload declaring a version this build does not know fails closed rather than being
tolerated.

## The commands

```
docket harness run --workspace DIR (--task TEXT | --task-file PATH) --model PROVIDER/ID
                   [--role implementer] [--timeout S] [--agent-id ID]
docket harness status TOKEN
```

stdout carries newline-delimited JSON and nothing else, line-buffered. Every log, warning and
human-facing word goes to stderr. Parse stdout line by line; the last line is always the result.

## Exit codes

This is the one place docket departs from its otherwise flat convention, deliberately, because a
program cannot read a printed message.

| Code | Meaning |
|---|---|
| 0 | The turn completed. The result line carries `status: "ok"` |
| 1 | The turn ran and ended `failed`, `blocked` or `cancelled` |
| 2 | Refused before any turn began. Exactly one result line with `status: "refused"`, no run record, no metadata written |

`docket harness status` stays flat: 0 for any successful lookup including `unknown`, 1 only for a
missing token.

## Two amendments you should know about

**Cancellation now reaches a running shell command.** Previously an already-running tool handler
was allowed to finish. That still holds for every handler except `bash`, which is now polled and
whose process group is killed on cancellation. Measured: a run whose hop sits inside a long command
terminalizes as cancelled in under three seconds.

**An approval that nobody can answer is now refused, not waited on.** Harness mode runs with the
refusing mode, so a tool call requiring human approval returns immediately with
`status: "blocked"` and a `blocked` object naming the tool, the call id, the policy id and the
reason. It does not create an approval record and does not wait.

## What this does not promise

One agent, one turn. Not a pod, not a fleet, not a server. There is no interactive approval path,
and adding one is a separate unbuilt feature by decision.

No dollar figures. `cost_usd` is always null. Token counts are measured and real; any money
number would be an estimate and is not published here.

A finished run's `status` reports the outcome but cannot recover the served model or the blocked
rule detail, because those existed only in the turn's in-memory result. Capture them from the
event stream while the run is live if you need them.

Nothing here asserts that any consumer integration works. That is the consumer's probe to run.
