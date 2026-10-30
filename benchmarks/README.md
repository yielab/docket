# Docket adoption benchmark

This development harness turns a fixed scenario and a Docket home's durable records into one
canonical JSONL attempt stream plus a deterministic aggregate. It checks that those records join,
count and normalize as the schema says. It does not run Docket: in the published baseline the
records are written by a scenario driver, not left behind by a product run. A deterministic fake
result is not evidence of model quality, market rank, or savings.

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
path-escaping, or mismatched input before replacing an existing output. `run` stages the JSONL and
the aggregate as temporary files beside their targets, then renames both; if the second rename
fails it restores the first.

## Where the published records come from

`benchmarks/scenarios/run.py` writes the run, task, session, audit and trace records itself,
including a fabricated `guardrail_block` trace event for the two denial cases, and the changed
target bytes in the cases that mutate. It calls the Docket CLI only for `run --pod demo --dry-run`,
`task answer` and `task show`. It imports no `docket` module, and no agent turn, tool
dispatch or policy decision runs. It sets each approval's creation time to the time of its
resolution, so approval latency is deterministic by construction rather than measured. The
`public_actions` labels in `evidence.json` are case data, not a record of calls.

## Published Wave 29 baseline

The [public adoption report](../docs/ADOPTION-EVIDENCE.md) links the canonical baseline and explains
its limits. Regenerate it from an exact commit, from a working tree with no uncommitted changes, with:

```sh
python benchmarks/results/regenerate.py \
  --source-commit COMMIT \
  --output OUTPUT \
  --repetitions 3
```

The command builds and installs that commit's wheel outside the checkout, runs the starter journey
and the seven scripted scenario cases without provider credentials, and removes its temporary
state. It refuses a dirty tree, and it writes the baseline to a staging directory that is renamed
into place only when complete.

## Scenario contract

A scenario records its own version, stable id and seed, `deterministic` or `live` measurement class,
source commit and artifact hashes, allowlisted runtime configuration, and one or more attempt
coordinates. Each attempt names exactly one run, joined task, and fresh session. Recovery attempts
also name a relative snapshot containing the stale task and its retained hops.

Runtime configuration is intentionally narrow: `adapter`, `model`, `token_budget`, and
`max_tool_calls`. Do not put credentials, headers, endpoint URLs, environment dumps, prompts, or
other free-form runtime data in a scenario.

## Provenance and interpretation

- Completion joins `state/docket-runs.json` `taskIds` to the project's Lead `TASK_LIST.json`; run success
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

Locators are relative to the supplied Docket home root (`DOCKET_HOME`), so runtime records sit under
`state/` (`state/docket-runs.json#run-one`, `state/audit.log#seq=1`). Output excludes raw prompts, secrets, home
paths, user/PID fields, approval tokens, tool arguments, handoff text, and backend raw objects.
Canonical identities exclude clocks, UUIDs, paths, process state, and measured elapsed duration.

## Adding Wave 29 scenarios

Copy the fixture layout under `benchmarks/fixtures/`, retain schema version `1.0.0`, and use fresh
run/task/session identities per attempt. Run the focused contract before publishing any result:

```sh
uv run pytest -q tests/agent/release/test_adoption_benchmark.py
```

Scenario additions must not weaken schema closure, privacy scans, or the rule that failed attempts
remain in the denominator. Invalid records must remain a no-op for existing outputs.
