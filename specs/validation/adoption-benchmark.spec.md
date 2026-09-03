# Adoption Benchmark Validation Specification

**Version**: 1.2.3
**Status**: Implemented
**Last Updated**: 2026-09-03

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

`usd` MUST be a non-negative canonical decimal string with exactly six fractional places.
`estimate` MUST be exactly `true`, and every pricing provenance field MUST be non-empty. A
measured/billed dollar mode is not part of version 1.0.0.

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

### 7. Adversarial governance and recovery journeys

`benchmarks/scenarios/run.py` MUST expose one credential-free repository-local command:

```text
python benchmarks/scenarios/run.py --output OUTPUT --repetitions 3
```

The command MUST execute exactly these scenario ids through public Docket CLI actions and the C3
benchmark subprocess: `allowed`, `policy-denied`, `approval-denied`, `approval-granted`,
`malformed-handoff`, `hard-crash-resume`, and `corrupt-primary-recovery`. Scenario definitions MUST
live under `benchmarks/scenarios/cases/`; the driver MUST NOT import or call `docket.core` or
`docket.edges` to manufacture an outcome. A deterministic loopback model or process boundary is
permitted, but no hosted provider, credential, subscription, destructive real command, port 8081,
or shared live state is part of the proof.

Each repetition MUST start with a unique fresh Docket home, workspace, temporary root, cache, and
loopback port. The driver MUST stop every child and listener before returning. Logical fixture ids
and normalized C3 records remain deterministic across repetitions; filesystem roots, ports, PIDs,
clocks, and approval tokens MUST NOT enter JSONL or aggregate bytes.

Every repetition directory MUST retain its scenario coordinate, Docket home, workspace target,
pre-action target bytes, C3 JSONL, aggregate, and a compact `evidence.json`. The root
`manifest.json` MUST use only relative, non-escaping paths and index the scenario id, repetition,
loopback port, public action labels, write count, before/after SHA-256 hashes, and those retained
artifacts. It MUST contain exactly one entry per scenario/repetition and no raw prompt, tool
argument, credential, approval token, absolute path, or provider payload.

The behavior table is normative:

| Scenario | Terminal benchmark result | Mutation / governance oracle |
| --- | --- | --- |
| `allowed` | completed, no handoff/recovery failure | target changes exactly once |
| `policy-denied` | incomplete, one prevented policy violation | target bytes unchanged |
| `approval-denied` | incomplete, one prevented policy violation and measured approval latency | target bytes unchanged |
| `approval-granted` | completed with measured approval latency | target changes exactly once after the grant |
| `malformed-handoff` | incomplete with one counted handoff failure | malformed content is never copied into benchmark output |
| `hard-crash-resume` | completed with stale claim observed, retained hops, and terminal resume | completed hops are not rerun; the target changes exactly once |
| `corrupt-primary-recovery` | completed through a public registry read | valid backup wins and exact malformed primary bytes remain in bounded quarantine |

For every entry, the referenced attempt and aggregate MUST validate under schema `1.0.0`; rebuilding
the aggregate from JSONL alone MUST be byte-identical. The three normalized attempt/aggregate pairs
for one scenario MUST also be byte-identical, proving that isolated runtime coordinates do not leak
into evidence. Denial target hashes MUST match; allowed/granted/crash target hashes MUST differ and
report `write_count=1`. Trace/audit locators MUST resolve within the retained home. The hard-crash
snapshot MUST contain only already completed hops and those hops MUST be an exact prefix of the
terminal task. Corrupt-primary recovery MUST preserve a valid `.bak`, one `.corrupt` containing the
exact malformed bytes, a valid mode-`0600` primary, and no `.tmp`.

### 8. Reproducible published baseline

`benchmarks/results/regenerate.py` MUST expose one credential-free command that regenerates the
published Wave 29 evidence from an exact committed source tree:

```text
python benchmarks/results/regenerate.py \
  --source-commit COMMIT \
  --output OUTPUT \
  --repetitions 3
```

The command MUST resolve `COMMIT` to a clean tracked Git commit, archive that exact tree into
temporary state, build its root wheel and sdist, calculate the wheel SHA-256, install the wheel
outside the checkout on Python 3.11, and run the C2 starter plus all seven C4 cases through that
artifact environment. Hosted credentials, a live provider, shared Docket state, and port 8081 MUST
not be used. Build, install, home, workspace, cache, temporary, and loopback state MUST be isolated
and removed after the requested output is complete.

Raw wheel identity is part of the published provenance, so the builder MUST ignore ambient Python
selection and build with uv-managed CPython 3.14.3. It MUST constrain Hatchling 1.32.0 and its full
build dependency closure through `benchmarks/results/build-constraints.txt`. It MUST then repack
the content-identical wheel at Deflate level 6 using checksum-pinned zlib-ng 2.3.3 with new
strategies disabled; installing and running the resulting wheel MUST remain on Python 3.11. Clean
regenerations started with different ambient `UV_PYTHON` values MUST produce the existing canonical
wheel SHA-256
`0fe67120737c4d09da3229c1182d8bf5474e96f7077476f997c98f7c67667fce`. Changing the published
baseline to accept build-interpreter or backend drift is forbidden.

The published baseline under `benchmarks/results/wave29/` MUST contain a canonical `manifest.json`
and relative locators for exactly eight scenario groups: `starter`, `allowed`, `policy-denied`,
`approval-denied`, `approval-granted`, `malformed-handoff`, `hard-crash-resume`, and
`corrupt-primary-recovery`. The starter group MUST retain both its denied and granted attempts;
therefore the complete baseline has nine attempts, five completions, and four failures. Each entry
MUST retain its C3-valid JSONL, aggregate, and compact evidence. Every attempt's source commit and
artifact SHA-256 MUST equal the manifest provenance; placeholder digests are invalid.

The manifest summary MUST be mechanically recomputable from the retained attempt records and MUST
include scenario, attempt, completion, failure, provider-reported token, tool-call, prevented-policy,
approval-latency observation, recovery, handoff-failure, stop-reason, and cost totals. Failed
attempts remain in every denominator. Unavailable dollars MUST remain `null`; deterministic fixture
cost `0.0` is not measured price evidence.

Two regenerations from the same commit MUST have the same relative file set and byte-identical
canonical records after applying only the manifest's closed timing comparison rule. The only
permitted exclusions are attempt `approval_latency_ms`, aggregate
`approval_latency_ms.total`, and separately retained `measurements.elapsed_ms`; the manifest MUST
name a bounded millisecond tolerance for them. No identity, outcome, count, token, tool, safety,
recovery, handoff, stop reason, provenance, path, or cost field may be normalized away or described
as byte-stable when it was measured from a clock.

`docs/ADOPTION-EVIDENCE.md` MUST link the manifest, raw records, schema, and exact source commit. It
MUST publish the complete attempt/failure table and distinguish deterministic contract evidence
from live model-quality or price evidence. README, compatibility, security, and the documentation
index MUST link that report without claiming a leaderboard, competitor rank, savings, production
success rate, or unavailable dollar value. Published bytes MUST exclude secrets, approval tokens,
raw prompts/tool arguments, absolute build/home paths, and provider payloads.

## Functions

`benchmarks/harness.py` owns scenario parsing, strict durable-record joins, attempt normalization,
canonical serialization, atomic output replacement, and aggregate reconstruction. It may import
public Docket data models for validation, but MUST NOT mutate or bypass any product runtime path.

`benchmarks/schema.json` owns the JSON Schema definitions for scenario, attempt, aggregate, cost,
locators, recovery, and their closed vocabularies. The Python validation and JSON Schema MUST agree;
neither may accept a record the other rejects.

## Testing

The base owning behavioral suite is `tests/python/test_adoption_benchmark.py`. It MUST use temporary
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

The C4 journey suite is `tests/python/test_adoption_adversarial_recovery.py`. It MUST invoke the
scenario driver as a subprocess with three repetitions, validate all retained C3 records and
side-effect oracles, prove cross-run isolation, and exercise public CLI evidence rather than mock a
product state transition. Before C4 implementation it MUST collect successfully and fail with an
explicit list of the missing driver/case files, not an import, collection, network, or fixture error.

The C6 publication suite is `tests/python/test_adoption_evidence.py`. It MUST validate the committed
baseline, rebuild every aggregate from JSONL, recompute the summary, reject placeholder provenance
and marketing overclaims, resolve every public link, scan published bytes for private data, and run
two exact-artifact regenerations. Before C6 implementation it MUST collect successfully and fail
with an explicit list of the missing regenerator, baseline manifest, and public report.

Every CI job that runs this suite MUST check out complete Git history. The baseline intentionally
pins an earlier exact source commit, so a depth-one checkout cannot validate or regenerate it and
MUST NOT be treated as a product failure.

The JSON Schema validator used by the C4 and C6 publication oracles MUST be an explicit development
dependency and MUST be installed in the dependency-floor test harness. The floor set itself remains
limited to runtime dependency bounds; test-only validation packages MUST NOT become runtime
dependencies merely to make CI collection succeed.

## Performance

The runner SHOULD stream JSONL input one record at a time and MUST bound every input file before
loading untrusted content. It MUST use only project/runtime dependencies and the Python standard
library; it MUST NOT add a telemetry, database, HTTP, benchmark-service, or pricing dependency.
Deterministic scenarios MUST use no network, hosted credentials, subscriptions, or shared port.

## Changelog

- **1.2.3 — 2026-09-03:** Pin the managed build interpreter, complete Hatchling closure, and
  checksum-verified zlib-ng compressor so ambient Python selection cannot change the published raw
  wheel identity.

- **1.2.2 — 2026-09-03:** Require the JSON Schema oracle as a declared test-only
  dependency and install it in the runtime-floor harness without adding it to Docket's runtime.

- **1.2.1 — 2026-09-03:** Require complete Git history in CI jobs that validate
  the pinned baseline source, preventing shallow checkout from making provenance tests vacuously
  fail before regeneration.

- **1.2.0 — 2026-09-03:** Ship the exact-artifact Wave 29 baseline, complete
  starter-plus-adversarial attempt set, mechanically derived public summary, bounded timing-only
  comparison rule, privacy boundary, public report, and publication oracle.

- **1.1.0 — 2026-09-02:** Ship the seven public adversarial governance and crash/recovery journeys,
  three-repetition isolation boundary, retained byte/record evidence, and scenario driver.

- **1.0.0 — 2026-09-02:** Ship the deterministic, versioned, privacy-preserving adoption benchmark
  over public durable Docket records, including its closed JSON Schema, canonical runner, minimal
  fixture, provenance map, atomic invalid-input behavior, and JSONL-only aggregate reconstruction.
