# Adoption evidence

This report publishes Docket's Wave 29 **deterministic contract evidence**. It shows that one exact
wheel completed or safely stopped the repository's starter, policy, approval, malformed-handoff,
and recovery fixtures. It does not measure model quality, production reliability, competitor
performance, or savings.

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

The generator archives that exact commit, builds its wheel and sdist, installs the wheel outside
the checkout on Python 3.11, and runs three isolated repetitions. It drives the artifact-installed
starter through both decisions and uses the same C3 normalization contract for its denied and
granted records. It also runs every adversarial/recovery case through the installed artifact.
Provider credentials and port 8081 are not used.

Two regenerations have the same file set and canonical content after excluding only approval
latency totals and wall-clock measurements. The [manifest](../benchmarks/results/wave29/manifest.json)
names those three timing fields and their bounded comparison tolerance. Published evidence omits
temporary state, approval identities, prompts, tool arguments, provider payloads, and credentials.

## Limits

These are deterministic fixtures against a local recording endpoint. They answer whether the
documented governance and recovery contracts held for this artifact. They do not establish how a
live model chooses tools, how often real workloads finish, what a provider bills, or how Docket
compares with another orchestration system. Re-run the scenarios with your own deployment and
workload before making an adoption decision.
