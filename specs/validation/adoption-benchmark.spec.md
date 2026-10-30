# Adoption Benchmark Validation Specification

**Version**: 2.3.1
**Status**: Implemented
**Last Updated**: 2026-10-30

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

The scenario, every attempt record, the aggregate, and the benchmark JSON Schema MUST declare
schema version `1.0.0`. Unknown versions MUST fail closed. JSONL MUST contain exactly one complete
JSON object per line; a blank line is invalid. The `aggregate` command additionally requires the
JSONL to be byte-identical to its canonical form (rule 5). Output objects MUST reject unknown fields
so raw source content cannot leak through an unmodelled property. A failing command prints
`benchmark error: <reason>` to stderr and exits 2.

### 2. Scenario coordinate and deterministic identity

A scenario MUST identify `scenario_id`, `scenario_version`, integer `seed`,
`measurement_class` (`deterministic` or `live`), source commit (lowercase 40 to 64 hex), source
artifact SHA-256, runtime name/version, a bounded allowlisted runtime configuration, and one or
more attempt coordinates. Each attempt coordinate MUST have a positive, unique ordinal and exact
`run_id`, `project`, `task_id`, and a `session_key` that no other attempt in the scenario uses. A
recovery case MUST additionally identify a relative, non-escaping snapshot of the stale task
record; every other coordinate carries `recovery_snapshot: null`. A coordinate also carries its
`cost` (rule 4).

`attempt_id` MUST be `sha256:` plus a SHA-256 derived only from the canonical normalized scenario
id, scenario version, seed, attempt ordinal, source provenance, measurement class, and allowlisted
runtime configuration. It MUST NOT depend on a clock, UUID, process/user identity, input/output
path, absolute home, filesystem order, or measured elapsed duration.

Runtime configuration output is limited to `adapter`, `model` (a `provider/model` id),
`token_budget`, and `max_tool_calls`. Secret-bearing or transport-bearing keys such as credentials,
tokens, headers, environment dumps, endpoint URLs, and arbitrary extras MUST be rejected rather
than copied.

### 3. Required attempt fields and live provenance

An attempt record MUST contain the following normalized fields:

- schema/record version, deterministic `attempt_id`, scenario coordinate, source provenance,
  runtime/configuration, measurement class, and attempt ordinal;
- `attempts`, `completed`, provider-reported input/output/total tokens, total and actually-executed
  tool calls, prevented policy violations, approval latency, crash/restart recovery, handoff
  failures, stop reason, cost, and relative `run`/`task`/`session`/`trace`/`audit`/
  `recovery_snapshot` locators.

The runner MUST derive those values as follows:

1. Read the selected run from `state/docket-runs.json`, require its `project` to match the coordinate and
   its `taskIds` to contain the selected task, then join that id to the selected project's Lead
   `TASK_LIST.json` (`state/workspaces/projects/<project>-lead/`). A run state by itself is
   insufficient: `completed=true` requires a `succeeded` run and a task status of `done`.
2. Sum positive `hops[].attempts` from that task. A task with no hop, or a missing, Boolean, zero,
   or negative attempt value, is invalid rather than silently defaulted.
3. Read only the selected session's (`state/sessions/<url-quoted session key>/session.json`) cumulative
   `usage.inputTokens` and `usage.outputTokens`; the record's `sessionKey` MUST equal the
   coordinate. Those are endpoint-reported counts accumulated within one session; `total_tokens`
   MUST equal their sum. Reusing one session key across the attempts of a scenario is invalid, and
   unrelated sessions MUST NOT affect the attempt.
4. Read `state/traces/<project>/<session key>.jsonl`; every record MUST carry the coordinate's project and
   session id. Pair `tool_call` and `tool_result` events by `callId` and tool name.
   `tool_calls.total` counts completed pairs, while `tool_calls.executed` counts only results with
   `executed=true`. An orphan, duplicate, or mismatched call/result is invalid.
5. Count prevented violations as the number of `guardrail_block` trace events plus the policy-backed
   `tool.deny` audit entries. An audit entry is policy-backed only when its detail text carries the
   selected project and a non-empty `policy_id` and a non-allow `policy_action`. The count is
   scoped to the selected project, not to the selected task. Approval requests and bare
   command-classifier denials are not policy violations.
6. Compute approval latency in integer milliseconds from a selected task's approval record
   (`state/approvals/*.json` whose `context.taskId` and `project` match) `created` timestamp to the
   matching terminal `approval.grant`/`approval.deny` audit timestamp, joined by the approval token
   in the audit detail. At most one approval may match a task; it MUST be in a terminal state
   (`granted` or `denied`) and have exactly one matching audit entry, or the attempt is invalid.
   Without an approval the latency is `null`. The approval token MAY be used only as an internal
   join key and MUST NOT appear in output or a locator.
7. A recovered attempt requires all four oracles: a relative snapshot whose task has
   `status=failed` and `failureKind=stale_claim`; one or more retained hop records that pass the
   handoff validation of item 8; a `stale_claim` trace event naming the task; and a final task in a
   terminal status (`done`, `failed`, `blocked`, or `cancelled`) whose hop list begins with the
   retained snapshot hops. A missing oracle, or a `stale_claim` event with no snapshot, makes the
   attempt invalid. `recovery.stale_claim_observed`, `retained_hops`, and `resumed_to_terminal`
   therefore always agree: `true`/positive/`true` for a recovered attempt and `false`/zero/`false`
   for any other.
8. Validate each persisted hop's `artifact`, when present, against the public `HandoffArtifact`
   shape. The `handoff_failures` count is the number of present artifacts that fail that
   validation. Artifact summaries, outputs, file paths, errors, verdict prose, and notes MUST NOT
   be copied.
9. `stop_reason=final_message` is valid only for a `succeeded` run whose task is `done` and whose
   persisted hops all have `ok=true`. Otherwise a cancelled run or task yields `run_cancelled`; a
   typed `stop_reason` in the last `session_end` trace event yields that reason; a
   `budget_exceeded` trace event yields `token_budget`; and with none of these the attempt is
   invalid. Free-text reason/error matching MUST NOT manufacture a stop reason. The closed
   vocabulary is `final_message`, `max_iterations`, `max_tool_calls`, `timeout`, `token_budget`,
   `truncated`, `backend_error`, `compaction_failed`, `context_fit`, `tool_denials`, and
   `run_cancelled`.

Every locator MUST be relative to the supplied Docket home root (the `DOCKET_HOME` that holds
`config/` and `state/`, per `specs/functional/workspace-structure.spec.md`) and use only a record id (`#<id>`), a
trace or session file, or an audit sequence suffix (`state/audit.log#seq=<n>`). Absolute paths and
approval-token filenames are forbidden.

### 4. Cost and measurement honesty

Cost comes only from the scenario coordinate; the runner never reads a dollar figure from a run,
task, or session record. Unavailable pricing MUST be represented as `cost: null`; Docket's runtime
`0.0` placeholder MUST NOT become a measured zero-dollar claim. A non-null cost MUST have this
complete shape:

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
`estimate` MUST be exactly `true`, and every pricing provenance field MUST be non-empty bounded
public text (no secret-shaped content). A measured/billed dollar mode is not part of version
1.0.0. The aggregate cost is non-null only when every attempt is priced; priced attempts that
disagree on pricing provenance are invalid.

### 5. Privacy and normalization boundary

The runner MUST use a field allowlist, not generic serialization of a source record. Raw prompts,
task descriptions, handoff summaries/notes/output/errors, secrets, absolute home paths, user/PID
fields, approval tokens, and raw or redacted tool arguments MUST be absent from attempt and aggregate
bytes. Before writing, the runner MUST reject output that contains the Docket home path, `/home/`,
`\Users\`, an approval token, or secret-shaped text. Provider/backend `raw` objects MUST NOT be
accepted as scenario configuration.

Canonical JSON uses UTF-8, lexicographically sorted object keys, compact separators, no NaN or
Infinity, and one trailing newline per document/JSONL record. Records are ordered by attempt ordinal;
aggregate grouping and locators use stable lexical ordering. Wall-clock fields are excluded from the
record. The one allowed non-deterministic comparison normalization is explicitly measured elapsed
duration (rule 8); no identity, count, outcome, provenance, or locator may be normalized away.

### 6. Failure atomicity

Invalid, partial, duplicate, path-escaping, privacy-violating, or provenance-mismatched scenario,
artifact, JSONL, or aggregate input MUST exit non-zero before replacing either requested output.
If a prior JSONL or aggregate exists, both MUST remain byte-for-byte unchanged. The two outputs MUST
be different files. Temporary files for both outputs are created beside their targets and fully
written before either target is renamed; the two renames then run back to back, and a failed
second rename restores the first output's prior bytes (or removes it if there were none), so a
failure to place the aggregate leaves the prior JSONL in place and exits 2.

The `aggregate` command MUST validate all JSONL records, reject duplicate attempt ids/ordinals and
mixed scenario/source/runtime provenance, recompute each `attempt_id`, and reproduce the same
aggregate using JSONL alone. It MUST NOT read the scenario, Docket home, trace, audit, run, task, or
session stores.

### 7. Adversarial governance and recovery journeys

The scenario driver MUST expose one credential-free repository-local command:

```text
python benchmarks/scenarios/run.py --output OUTPUT --repetitions 3
```

`OUTPUT` MUST NOT already exist. The command MUST execute exactly these scenario ids, one case file
each under `benchmarks/scenarios/cases/`: `allowed`, `policy-denied`, `approval-denied`,
`approval-granted`, `malformed-handoff`, `hard-crash-resume`, and `corrupt-primary-recovery`. For
each repetition the driver writes the run, task, session, trace, and snapshot records itself as
fixtures, invokes public Docket CLI actions only where a case needs one (`docket run --pod demo
--dry-run` to provision the pod, `docket task answer --option approve_once` or `--option deny` for the two approval
cases, `docket task show` to read the registry in the corrupt-primary case), and normalizes the
result with the benchmark subprocess. The driver does not import any `docket` module. The
`public_actions` labels in evidence are case data, not a record of the calls made. The driver
itself writes the changed target bytes in the cases that mutate; the product does not. No hosted
provider, credential, subscription, destructive real command, model server, port 8081, or shared
live state is part of the proof.

Each repetition MUST start with a unique fresh Docket home, workspace, temporary root, and cache
directory. The port recorded for a repetition is a unique label from a bounded range that excludes
8081; the driver opens no listener. Logical fixture ids and normalized records remain
deterministic across repetitions; filesystem roots, ports, PIDs, clocks, and approval tokens MUST
NOT enter JSONL or aggregate bytes.

Every repetition directory MUST retain its scenario coordinate, Docket home, workspace target,
pre-action target bytes, JSONL, aggregate, and a compact `evidence.json` (`scenario_id`,
`repetition`, `public_actions`, `write_count`, `before_sha256`, `after_sha256`,
`malformed_primary_sha256`). The root `manifest.json` (`schema_version`, `repetitions`, `entries`)
MUST use only relative, non-escaping paths and contain exactly one entry per scenario and
repetition, each holding `scenario_id`, `repetition`, `port`, and the relative `paths` of the
retained home, workspace, before, target, scenario, jsonl, aggregate, and evidence artifacts. The
action labels, write count, and hashes live in `evidence.json`. Neither file contains a raw prompt,
tool argument, credential, approval token, absolute path, or provider payload.

The behavior table is normative:

| Scenario | Terminal benchmark result | Mutation / governance oracle |
| --- | --- | --- |
| `allowed` | completed, no handoff/recovery failure | target changes exactly once |
| `policy-denied` | incomplete, one prevented policy violation | target bytes unchanged |
| `approval-denied` | incomplete, one prevented policy violation and a measured approval latency | target bytes unchanged |
| `approval-granted` | completed with a measured approval latency | target changes exactly once after the grant |
| `malformed-handoff` | incomplete with one counted handoff failure | malformed content is never copied into benchmark output |
| `hard-crash-resume` | completed with stale claim observed, retained hops, and terminal resume | the retained hops are an exact prefix of the terminal task; the target changes exactly once |
| `corrupt-primary-recovery` | completed through a public registry read | valid backup wins and exact malformed primary bytes remain in bounded quarantine |

For every entry, the referenced attempt and aggregate MUST validate under schema `1.0.0`; rebuilding
the aggregate from JSONL alone MUST be byte-identical. The three normalized attempt/aggregate pairs
for one scenario MUST also be byte-identical, proving that isolated runtime coordinates do not leak
into evidence. Denial target hashes MUST match; allowed/granted/crash target hashes MUST differ and
report `write_count=1`. Trace/audit locators MUST resolve within the retained home. The hard-crash
snapshot MUST contain only already completed hops and those hops MUST be an exact prefix of the
terminal task. Corrupt-primary recovery MUST preserve a valid `.bak`, one `.corrupt` containing the
exact malformed bytes, a valid mode-`0600` primary, and no `.tmp`. The approval latency of the two
approval cases is deterministic by construction: the driver sets the approval's `created` to the
audit timestamp of its resolution.

### 8. Reproducible published baseline

The baseline regenerator MUST expose one credential-free command that regenerates the published
evidence from an exact committed source tree:

```text
python benchmarks/results/regenerate.py \
  --source-commit COMMIT \
  --output OUTPUT \
  --repetitions 3
```

`OUTPUT` MUST NOT already exist and `--repetitions` MUST be 3. The command MUST refuse, before
building anything, when the working tree has uncommitted changes, because the build constraints and
the wheel canonicalizer are read from the working tree and not from the archived commit. It MUST
resolve `COMMIT` to
a full commit SHA, archive that exact tree into temporary state, build its root wheel and sdist,
calculate the wheel SHA-256, install the wheel (after the starter's pinned requirements) outside
the checkout on Python 3.11, and run the starter journey plus all seven scenario cases through that
artifact environment, using the harness and driver from the archived tree. Hosted credentials, a
live provider, shared Docket state, and port 8081 MUST NOT be used. Build, install, home,
workspace, cache, temporary, and loopback state MUST be isolated and removed after the requested
output is complete. Regeneration is not offline: it needs `uv`, `git`, and `cmake`, lets `uv`
install the build Python, and downloads the pinned compressor source.

Raw wheel identity is part of the published provenance, so the builder MUST ignore ambient Python
selection and build with uv-managed CPython 3.14.3. It MUST constrain Hatchling 1.32.0 and its full
build dependency closure through `benchmarks/results/build-constraints.txt`. It MUST then repack
the content-identical wheel at Deflate level 6 using the checksum-pinned zlib-ng 2.3.3 source built
with new strategies disabled; installing and running the resulting wheel MUST remain on Python
3.11. Clean regenerations started with different ambient `UV_PYTHON` values MUST produce the
existing canonical wheel SHA-256
`722cc9adc4afd6714479825e877d3b59ec80928ad11173513aa46a1456bb9d9e`. Changing the published
baseline to accept build-interpreter or backend drift is forbidden.

The published baseline under `benchmarks/results/wave29/` MUST contain a canonical `manifest.json`
and relative locators for exactly eight scenario groups: `starter`, `allowed`, `policy-denied`,
`approval-denied`, `approval-granted`, `malformed-handoff`, `hard-crash-resume`, and
`corrupt-primary-recovery`. The starter group MUST retain both its denied and granted attempts;
therefore the complete baseline has nine attempts, five completions, and four failures. Each entry
MUST retain its schema-valid JSONL, aggregate, compact evidence, and `measurements.json`. Every
attempt's source commit and artifact SHA-256 MUST equal the manifest provenance; placeholder digests
are invalid. The starter's two attempt records are derived from the `approval-denied` and
`approval-granted` records with the starter's measured token usage; the harness is not run over the
starter's own home.

The manifest summary MUST be mechanically recomputable from the retained attempt records and MUST
include scenario, attempt, completion, failure, provider-reported token, tool-call, prevented-policy,
approval-latency observation, recovery, handoff-failure, stop-reason, and cost totals. Failed
attempts remain in every denominator. Unavailable dollars MUST remain `null`; deterministic fixture
cost `0.0` is not measured price evidence.

Two regenerations from the same commit MUST have the same relative file set and byte-identical
canonical records after applying only the manifest's closed timing comparison rule. The only
permitted exclusions are attempt `approval_latency_ms`, aggregate
`approval_latency_ms.total`, and separately retained `measurements.elapsed_ms`; the manifest MUST
name a bounded millisecond tolerance (5000) for them. No identity, outcome, count, token, tool,
safety, recovery, handoff, stop reason, provenance, path, or cost field may be normalized away or
described as byte-stable when it was measured from a clock.

`docs/ADOPTION-EVIDENCE.md` MUST link the manifest, raw records, schema, and exact source commit. It
MUST state that the driver wrote the run, task, session, audit and trace records, that the
`guardrail_block` events are fabricated by the driver, that the CLI is called only for `run --pod
demo --dry-run`, `task answer` and `task show`, and that the approval latency is set
by the driver; no sentence in it or in `benchmarks/README.md` may present the records as a product
run. It MUST publish the complete attempt/failure table and distinguish deterministic contract evidence
from live model-quality or price evidence. README, compatibility, security, and the documentation
index MUST link that report without claiming a leaderboard, competitor rank, savings, production
success rate, or unavailable dollar value. Published bytes MUST exclude secrets, approval tokens,
raw prompts/tool arguments, absolute build/home paths, and provider payloads.

## Functions

The benchmark runner owns scenario parsing, strict durable-record joins, attempt normalization,
canonical serialization, atomic output replacement, and aggregate reconstruction. It imports the
public `HandoffArtifact` model for validation, but MUST NOT mutate or bypass any product runtime
path.

The benchmark JSON Schema owns the definitions for scenario, attempt, aggregate, cost, locators,
recovery, and their closed vocabularies. The Python validation and the JSON Schema MUST agree;
neither may accept a record the other rejects.

The scenario driver owns the seven case definitions and the retained per-repetition evidence. The
baseline regenerator owns the exact-commit build, the wheel canonicalization, and the published
manifest.

## Testing

The base suite MUST use temporary Docket homes and invoke the public script commands as
subprocesses. Its representative fixture MUST include a joined run/task, a fresh measured-usage
session plus unrelated noise usage, paired allowed and denied tool calls, a guardrail block, a
policy-backed audit denial, a resolved approval, a stale claim snapshot and trace followed by a
terminal resumed task, and valid plus invalid handoff artifacts containing privacy sentinels.

Tests MUST prove:

- exact normalized field provenance and schema validation;
- byte-stable deterministic reruns and JSONL-only aggregate reproduction;
- unknown pricing remains null and an explicit estimate requires complete versioned provenance;
- source prompts, secrets, home paths, approval tokens, and tool arguments never appear;
- malformed, partial, duplicate, mismatched, and reused-session inputs preserve prior outputs.

The journey suite MUST invoke the scenario driver as a subprocess with three repetitions, with
hosted-credential sentinels and a dead proxy in its environment and an inherited `DOCKET_HOME` that
must stay unused. It MUST validate all retained records and side-effect oracles, prove cross-run
isolation, and scan the published bytes for the sentinels and paths.

The publication suite MUST validate the committed baseline, rebuild every aggregate from JSONL,
recompute the summary, reject placeholder provenance and marketing overclaims, resolve every public
link, scan published bytes for private data, check the pinned build toolchain, and run exact-artifact
regenerations under different ambient build interpreters.

Every CI job that runs these suites (`python`, `floors`, `macos`) MUST check out complete Git
history. The baseline intentionally pins an earlier exact source commit, so a depth-one checkout
cannot validate or regenerate it and MUST NOT be treated as a product failure.

The JSON Schema validator used by the journey and publication oracles MUST be an explicit
development dependency and MUST be installed in the dependency-floor test harness. The floor set
itself remains limited to runtime dependency bounds; test-only validation packages MUST NOT become
runtime dependencies merely to make CI collection succeed.

## Performance

The runner MUST bound every input file (16 MiB) before loading untrusted content; it reads each
bounded file whole. It MUST use only project/runtime dependencies and the Python standard library;
it MUST NOT add a telemetry, database, HTTP, benchmark-service, or pricing dependency. The harness
and the scenario driver MUST use no network, hosted credentials, subscriptions, or shared port; only
the baseline regenerator downloads anything (rule 8).

## Implementation

- `benchmarks/harness.py`: the `run` and `aggregate` commands, validation, joins, canonical output.
  Imports `HandoffArtifact` from `src/docket/kernel/handoff.py`.
- `benchmarks/schema.json`: the JSON Schema (`version` 1.0.0).
- `benchmarks/scenarios/run.py`, `benchmarks/scenarios/cases/*.json`: the scenario driver and cases.
- `benchmarks/results/regenerate.py`, `benchmarks/results/canonicalize_wheel.py`,
  `benchmarks/results/build-constraints.txt`: the baseline regenerator and its pinned toolchain.
- `benchmarks/results/wave29/`: the published baseline; `docs/ADOPTION-EVIDENCE.md`: its report.
- `examples/starter/`: the starter journey the baseline runs.
- `tests/agent/release/test_adoption_benchmark.py`: the base suite.
- `tests/agent/release/test_adoption_adversarial_recovery.py`: the journey suite.
- `tests/agent/release/test_adoption_evidence.py`: the publication suite.
- `tests/integration/product/test_adoption_tools.py`: output placement and the clean-tree refusal, in
  the default suite.
- `.github/workflows/ci.yml`, `pyproject.toml`: full-history checkouts and the `jsonschema`
  development dependency.
