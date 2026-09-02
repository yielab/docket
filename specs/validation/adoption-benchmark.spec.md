# Adoption Benchmark Validation Specification

**Version**: 1.0.0
**Status**: Draft (RED contract; implementation absent)
**Last Updated**: 2026-09-02

## Purpose

This specification defines the versioned, machine-readable contract for Docket's adoption
benchmark. The benchmark converts one fixed scenario plus public, durable Docket records into
canonical per-attempt JSONL and a deterministic aggregate JSON document. It provides reproducible
contract evidence; deterministic fake-model results do **not** measure or predict model quality.

The benchmark is a development harness, not a telemetry service. It does not add a product metric,
write into Docket's runtime stores, synchronize prices, rank competitors, or publish a savings
claim.

## Rules

### 1. Public actions and versioning

The runner MUST expose these repository-local commands:

```text
python benchmarks/harness.py run \
  --scenario SCENARIO.json \
  --docket-home DOCKET_HOME \
  --jsonl ATTEMPTS.jsonl \
  --aggregate AGGREGATE.json

python benchmarks/harness.py aggregate \
  --jsonl ATTEMPTS.jsonl \
  --aggregate AGGREGATE.json
```

The scenario, every attempt record, the aggregate, and `benchmarks/schema.json` MUST declare
schema version `1.0.0`. Unknown versions MUST fail closed. JSONL MUST contain exactly one complete
JSON object per non-empty line. Output objects MUST reject unknown fields so raw source content
cannot leak through an unmodelled property.

### 2. Scenario coordinate and deterministic identity

A scenario MUST identify `scenario_id`, `scenario_version`, integer `seed`,
`measurement_class` (`deterministic` or `live`), source commit, source artifact SHA-256, runtime
name/version, a bounded allowlisted runtime configuration, and one or more attempt coordinates.
Each attempt coordinate MUST have a positive, unique ordinal and exact `run_id`, `project`,
`task_id`, and fresh `session_key`. A recovery case MUST additionally identify a relative snapshot
of the stale task record.

`attempt_id` MUST be a SHA-256 identifier derived only from the canonical normalized scenario id,
scenario version, seed, attempt ordinal, source provenance, measurement class, and allowlisted
runtime configuration. It MUST NOT depend on a clock, UUID, process/user identity, input/output
path, absolute home, filesystem order, or measured elapsed duration.

Runtime configuration output is limited to `adapter`, `model`, `token_budget`, and
`max_tool_calls`. Secret-bearing or transport-bearing keys such as credentials, tokens, headers,
environment dumps, endpoint URLs, and arbitrary extras MUST be rejected rather than copied.

### 3. Required attempt fields and live provenance

An attempt record MUST contain the following normalized fields:

- schema/record version, deterministic `attempt_id`, scenario coordinate, source provenance,
  runtime/configuration, measurement class, and attempt ordinal;
- `attempts`, `completed`, provider-reported input/output/total tokens, total and actually-executed
  tool calls, prevented policy violations, approval latency, crash/restart recovery, handoff
  failures, stop reason, cost, and relative trace/audit/source locators.

The runner MUST derive those values as follows:

1. Read the selected run from `docket-runs.json`, require its `taskIds` to contain the selected
   task, then join that id to the selected project's Lead `TASK_LIST.json`. A run state by itself is
   insufficient: `completed=true` requires a succeeded run and a terminal task status of `done`.
2. Sum positive `hops[].attempts` from that task. Missing, Boolean, zero, or negative attempt values
   are invalid rather than silently defaulted.
3. Read only the selected fresh session's cumulative `usage.inputTokens` and
   `usage.outputTokens`. Those are endpoint-reported counts accumulated within one session;
   `total_tokens` MUST equal their sum. Reusing one session key across benchmark attempts is invalid,
   and unrelated sessions MUST NOT affect the attempt.
4. Pair trace `tool_call` and `tool_result` records by `callId`. `tool_calls.total` counts completed
   pairs, while `tool_calls.executed` counts only results with `executed=true`. An orphan, duplicate,
   or mismatched call/result is invalid.
5. Count prevented violations only from `guardrail_block` trace events and policy-backed
   `tool.deny` audit entries whose structured detail contains a non-empty `policy_id` and a
   non-allow `policy_action`. Approval requests and bare command-classifier denials are not policy
   violations.
6. Compute approval latency in integer milliseconds from a selected task's pending approval record
   `created` timestamp to the matching terminal `approval.grant`/`approval.deny` audit timestamp.
   The approval token MAY be used only as an internal join key and MUST NOT appear in output or a
   locator.
7. A recovered attempt requires all four oracles: a relative snapshot with
   `failureKind=stale_claim`; one or more retained valid hop records; a matching `stale_claim` trace
   event; and a final terminal task whose hop list begins with the retained snapshot hops.
   `recovery.stale_claim_observed`, `retained_hops`, and `resumed_to_terminal` MUST report those
   independently. A non-recovery attempt reports false/zero/false.
8. Validate each persisted hop's `artifact` against the public `HandoffArtifact` shape. The
   `handoff_failures` count is the number of present artifacts that fail that validation. Artifact
   summaries, outputs, file paths, errors, verdict prose, and notes MUST NOT be copied.
9. `stop_reason=final_message` is valid only for a completed task whose persisted hops succeeded.
   Other stop reasons require an unambiguous typed durable event. Free-text reason/error matching
   MUST NOT manufacture a stop reason.

Every locator MUST be relative to the supplied Docket home and use only a record id, trace line,
or audit sequence/hash suffix. Absolute paths and approval-token filenames are forbidden.

### 4. Cost and measurement honesty

Unavailable pricing MUST be represented as `cost: null`; Docket's runtime `0.0` placeholder MUST
NOT become a measured zero-dollar claim. A non-null cost MUST have this complete shape:

```json
{
  "usd": "0.001230",
  "estimate": true,
  "pricing": {
    "source": "fixture-pricing",
    "version": "2026-09-02",
    "assumption": "input and output tokens priced independently"
  }
}
```

`usd` MUST be a non-negative canonical decimal string. `estimate` MUST be exactly `true`, and every
pricing provenance field MUST be non-empty. A measured/billed dollar mode is not part of version
1.0.0.

### 5. Privacy and normalization boundary

The runner MUST use a field allowlist, not generic serialization of a source record. Raw prompts,
task descriptions, handoff summaries/notes/output/errors, secrets, absolute home paths, user/PID
fields, approval tokens, and raw or redacted tool arguments MUST be absent from attempt and aggregate
bytes. Provider/backend `raw` objects MUST NOT be accepted as scenario configuration.

Canonical JSON uses UTF-8, lexicographically sorted object keys, compact separators, no NaN or
Infinity, and one trailing newline per document/JSONL record. Records are ordered by attempt ordinal;
aggregate grouping and locators use stable lexical ordering. Wall-clock fields are excluded. The one
allowed non-deterministic comparison normalization is explicitly measured elapsed duration; no
identity, count, outcome, provenance, or locator may be normalized away.

### 6. Failure atomicity

Invalid, partial, duplicate, path-escaping, privacy-violating, or provenance-mismatched scenario,
artifact, JSONL, or aggregate input MUST exit non-zero before replacing either requested output.
If a prior JSONL or aggregate exists, both MUST remain byte-for-byte unchanged. Temporary files MUST
remain beside their target and be atomically replaced only after the complete output validates.

The `aggregate` command MUST validate all JSONL records, reject duplicate attempt ids/ordinals and
mixed scenario/source/runtime provenance, and reproduce the same aggregate using JSONL alone. It
MUST NOT read the scenario, Docket home, trace, audit, run, task, or session stores.

## Functions

`benchmarks/harness.py` owns scenario parsing, strict durable-record joins, attempt normalization,
canonical serialization, atomic output replacement, and aggregate reconstruction. It may import
public Docket data models for validation, but MUST NOT mutate or bypass any product runtime path.

`benchmarks/schema.json` owns the JSON Schema definitions for scenario, attempt, aggregate, cost,
locators, recovery, and their closed vocabularies. The Python validation and JSON Schema MUST agree;
neither may accept a record the other rejects.

## Testing

The owning behavioral suite is `tests/python/test_adoption_benchmark.py`. It MUST use temporary
Docket homes and invoke the public script commands as subprocesses. The representative fixture MUST
include a joined run/task, a fresh measured-usage session plus unrelated noise usage, paired allowed
and denied tool calls, a guardrail block, a policy-backed audit denial, a resolved approval, a stale
claim snapshot and trace followed by a terminal resumed task, and valid plus invalid handoff
artifacts containing privacy sentinels.

Tests MUST prove:

- exact normalized field provenance and schema validation;
- byte-stable deterministic reruns and JSONL-only aggregate reproduction;
- unknown pricing remains null and an explicit estimate requires complete versioned provenance;
- source prompts, secrets, home paths, approval tokens, and tool arguments never appear;
- malformed, partial, duplicate, mismatched, and reused-session inputs preserve prior outputs;
- live `_metrics.py` conventions are not reused where they collapse unavailable cost to zero or mix
  approval requests into guardrail counts.

The RED command is:

```text
uv run pytest -q tests/python/test_adoption_benchmark.py
```

Before implementation it MUST collect successfully and fail because `benchmarks/schema.json` and
`benchmarks/harness.py` are absent.

## Performance

The runner SHOULD stream JSONL input one record at a time and MUST bound every input file before
loading untrusted content. It MUST use only project/runtime dependencies and the Python standard
library; it MUST NOT add a telemetry, database, HTTP, benchmark-service, or pricing dependency.
Deterministic scenarios MUST use no network, hosted credentials, subscriptions, or shared port.

## Changelog

- **1.0.0 — 2026-09-02:** Define the RED contract for a deterministic, versioned, privacy-preserving
  adoption benchmark over public durable Docket records, including provenance, atomic failure, and
  JSONL-only aggregate reconstruction. Implementation is intentionally absent in this commit.
