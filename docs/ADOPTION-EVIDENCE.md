# Adoption evidence

This report publishes Docket's Wave 29 **deterministic contract evidence**. It is scripted fixture
data, not a record of the product running a task. A driver writes the run, task, session, audit and
trace records that Docket would leave behind, and a benchmark harness checks that those records
join, count and normalize as the benchmark contract says. It does not measure model quality,
production reliability, competitor performance, or savings.

## What produced these records

- **The driver writes the records.** Every attempt record, the starter's two included, derives from
  records that [`benchmarks/scenarios/run.py`](../benchmarks/scenarios/run.py) wrote: the run, task, session and
  trace records, including every `tool_call`, `tool_result` and `guardrail_block` trace event.
  The `guardrail_block` in the policy-denied and approval-denied groups is fabricated by the driver;
  no policy hook evaluated a tool call. The driver also writes the changed target bytes in the
  cases that mutate.
- **The CLI is called four ways, and no more.** The driver runs `docket run --pod demo --dry-run`
  to provision the pod, `docket task approve` and `docket task deny` to resolve a pre-written
  approval record, and `docket task show` to read the registry in the corrupt-primary case. It
  does not import a `docket` module. No agent turn, tool dispatch, policy decision or dispatch
  hop runs.
- **The `public_actions` labels are case data.** The labels in each group's `evidence.json`, such as
  `pipeline.run` and `approval.grant`, name what the case stands for. They are not a record of calls
  made, and `pipeline.run` and `pipeline.run.resume` were not executed.
- **Approval latency is set, not measured.** The driver rewrites the approval's creation time to
  the audit time of its resolution, so the two approval cases report a deterministic latency by
  construction.
- **The starter is the one group that ran the installed wheel end to end.** The starter journey
  drives the installed artifact through a denial and a grant against a deterministic loopback
  fake. Its two attempt records are still derived from the `approval-denied` and
  `approval-granted` driver records; only the token counts are taken from the starter's session.
- **The harness reads files.** [`benchmarks/harness.py`](../benchmarks/harness.py) turns the
  records into attempts and an aggregate. Everything it counts was either written by the driver or
  written by one of the four CLI calls above.

The groups therefore show that the benchmark's join, count and privacy rules hold over scripted
inputs, and that those four CLI commands accept and resolve the records they were given. They do
not show that a live pipeline blocks, denies, recovers or completes.

## Result

The baseline contains **9 attempts**, **5 completions**, and **4 failures** across eight scenario
groups. A failure here means the fixture reached its expected safe terminal state; failed attempts
remain in the denominator.

| Scenario | Attempts | Completions | Expected observation | Records |
| --- | ---: | ---: | --- | --- |
| starter | 2 | 1 | Denial preserves the workspace; grant performs one mutation | [attempts](../benchmarks/results/wave29/starter/attempts.jsonl), [aggregate](../benchmarks/results/wave29/starter/aggregate.json), [evidence](../benchmarks/results/wave29/starter/evidence.json) |
| allowed | 1 | 1 | Allowed action completes once | [attempts](../benchmarks/results/wave29/allowed/attempts.jsonl), [aggregate](../benchmarks/results/wave29/allowed/aggregate.json), [evidence](../benchmarks/results/wave29/allowed/evidence.json) |
| policy-denied | 1 | 0 | Policy prevents the mutation | [attempts](../benchmarks/results/wave29/policy-denied/attempts.jsonl), [aggregate](../benchmarks/results/wave29/policy-denied/aggregate.json), [evidence](../benchmarks/results/wave29/policy-denied/evidence.json) |
| approval-denied | 1 | 0 | Denial prevents the mutation | [attempts](../benchmarks/results/wave29/approval-denied/attempts.jsonl), [aggregate](../benchmarks/results/wave29/approval-denied/aggregate.json), [evidence](../benchmarks/results/wave29/approval-denied/evidence.json) |
| approval-granted | 1 | 1 | Grant permits one mutation | [attempts](../benchmarks/results/wave29/approval-granted/attempts.jsonl), [aggregate](../benchmarks/results/wave29/approval-granted/aggregate.json), [evidence](../benchmarks/results/wave29/approval-granted/evidence.json) |
| malformed-handoff | 1 | 0 | Invalid typed handoff stops cleanly | [attempts](../benchmarks/results/wave29/malformed-handoff/attempts.jsonl), [aggregate](../benchmarks/results/wave29/malformed-handoff/aggregate.json), [evidence](../benchmarks/results/wave29/malformed-handoff/evidence.json) |
| hard-crash-resume | 1 | 1 | Stale work resumes without losing retained hops | [attempts](../benchmarks/results/wave29/hard-crash-resume/attempts.jsonl), [aggregate](../benchmarks/results/wave29/hard-crash-resume/aggregate.json), [evidence](../benchmarks/results/wave29/hard-crash-resume/evidence.json) |
| corrupt-primary-recovery | 1 | 1 | Backup recovery quarantines malformed primary bytes | [attempts](../benchmarks/results/wave29/corrupt-primary-recovery/attempts.jsonl), [aggregate](../benchmarks/results/wave29/corrupt-primary-recovery/aggregate.json), [evidence](../benchmarks/results/wave29/corrupt-primary-recovery/evidence.json) |

The four non-completing observations are `starter` attempt 1, `policy-denied`, `approval-denied`,
and `malformed-handoff`. The retained totals are 108 provider-reported fixture tokens, eight tool
calls with five executed, two prevented policy violations, four approval-latency observations, one
successful stale-claim recovery, and one malformed-handoff failure. Dollar cost is **cost unavailable**
because the deterministic provider supplies no price evidence.

## Provenance and reproduction

- Source commit: [`82a3239980bbda3673fdd8030751f1342bcab132`](https://github.com/yielab/docket/commit/82a3239980bbda3673fdd8030751f1342bcab132)
- Artifact: `docket-0.2.0b1-py3-none-any.whl`
- Artifact SHA-256: `0fe67120737c4d09da3229c1182d8bf5474e96f7077476f997c98f7c67667fce`
- Canonical index and complete summary: [manifest](../benchmarks/results/wave29/manifest.json)
- Attempt and aggregate contract: [benchmark schema](../benchmarks/schema.json)

Regenerate from the repository root:

```sh
python benchmarks/results/regenerate.py \
  --source-commit 82a3239980bbda3673fdd8030751f1342bcab132 \
  --output ./wave29-reproduced \
  --repetitions 3
```

The generator archives that exact commit and builds it with uv-managed CPython 3.14.3 plus the
fully pinned Hatchling closure in
[`build-constraints.txt`](../benchmarks/results/build-constraints.txt). It canonicalizes the wheel
at Deflate level 6 with checksum-verified zlib-ng 2.3.3 before hashing it, then installs the wheel
outside the checkout on Python 3.11 and runs three isolated repetitions. Reproduction therefore
requires `uv`, CMake, a C compiler, and network access to the pinned Python/package sources and the
checksum-verified zlib-ng source archive. It drives the artifact-installed starter through both
decisions and uses the same C3 normalization contract for its denied and granted records. It also
runs the scenario driver, whose records are scripted as described above, with the installed
artifact supplying the four CLI calls. The regenerator refuses to start when the working tree has
uncommitted changes, because the build constraints and the wheel canonicalizer are read from it.
Provider credentials and port 8081 are not used.

Two regenerations have the same file set and canonical content after excluding only approval
latency totals and wall-clock measurements. The [manifest](../benchmarks/results/wave29/manifest.json)
names those three timing fields and their bounded comparison tolerance. Published evidence omits
temporary state, approval identities, prompts, tool arguments, provider payloads, and credentials.

## Limits

These are deterministic fixtures: scripted records plus the four CLI calls listed above, and one
starter journey against a loopback fake. They answer whether the benchmark's own contract held over
those inputs and whether those CLI commands handled them. They do not establish how a
live model chooses tools, how often real workloads finish, what a provider bills, or how Docket
compares with another orchestration system. Re-run the scenarios with your own deployment and
workload before making an adoption decision.
