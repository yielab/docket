# Docket adoption benchmark

This development harness turns a fixed scenario and Docket's public durable records into one
canonical JSONL attempt stream plus a deterministic aggregate. It measures contract behavior and
provenance. A deterministic fake result is not evidence of model quality, market rank, or savings.

Schema version `1.0.0` is defined in `schema.json`. The runner uses only Docket's existing runtime
dependencies and the Python standard library.

## Run the included deterministic fixture

From the repository root:

```sh
out="$(mktemp -d)"
uv run python benchmarks/harness.py run \
  --scenario benchmarks/fixtures/minimal/scenario.json \
  --docket-home benchmarks/fixtures/minimal/docket-home \
  --jsonl "$out/attempts.jsonl" \
  --aggregate "$out/aggregate.json"
```

Rebuild the aggregate without the scenario or Docket home:

```sh
uv run python benchmarks/harness.py aggregate \
  --jsonl "$out/attempts.jsonl" \
  --aggregate "$out/rebuilt.json"
cmp "$out/aggregate.json" "$out/rebuilt.json"
```

The two aggregate files are byte-identical. Both commands reject malformed, duplicate, partial,
path-escaping, or mismatched input before replacing an existing output.

## Scenario contract

A scenario records its own version, stable id and seed, `deterministic` or `live` measurement class,
source commit and artifact hashes, allowlisted runtime configuration, and one or more attempt
coordinates. Each attempt names exactly one run, joined task, and fresh session. Recovery attempts
also name a relative snapshot containing the stale task and its retained hops.

Runtime configuration is intentionally narrow: `adapter`, `model`, `token_budget`, and
`max_tool_calls`. Do not put credentials, headers, endpoint URLs, environment dumps, prompts, or
other free-form runtime data in a scenario.

## Provenance and interpretation

- Completion joins `docket-runs.json` `taskIds` to the project's Lead `TASK_LIST.json`; run success
  alone is not completion.
- Attempts are the sum of positive persisted `hops[].attempts`.
- Provider-reported token counts come from the named fresh session's cumulative usage. Other
  sessions are never folded into an attempt.
- Tool totals require paired `tool_call`/`tool_result` trace records; `executed` counts only an
  explicit true result.
- Prevented violations count `guardrail_block` plus policy-backed `tool.deny` audit entries. An
  approval request or classifier-only denial is not a policy violation.
- Approval latency joins the approval creation time to its terminal audit record internally. The
  approval token is never emitted.
- Recovery requires a stale-claim snapshot, retained valid hops, a matching trace event, and the
  terminal task preserving that hop prefix.
- Handoff failures are failed validations against Docket's `HandoffArtifact`; handoff content is
  never emitted.
- Dollar cost is `null` unless the scenario supplies an explicit estimate. Every non-null amount is
  estimate-labelled and includes a pricing source, version, and assumption. Docket's runtime `0.0`
  placeholder is not treated as measured cost.

Locators are relative to the supplied Docket home. Output excludes raw prompts, secrets, home
paths, user/PID fields, approval tokens, tool arguments, handoff text, and backend raw objects.
Canonical identities exclude clocks, UUIDs, paths, process state, and measured elapsed duration.

## Adding Wave 29 scenarios

Copy the fixture layout under `benchmarks/fixtures/`, retain schema version `1.0.0`, and use fresh
run/task/session identities per attempt. Run the focused contract before publishing any result:

```sh
uv run pytest -q tests/python/test_adoption_benchmark.py
```

Scenario additions must not weaken schema closure, privacy scans, or the rule that failed attempts
remain in the denominator. Invalid records must remain a no-op for existing outputs.
