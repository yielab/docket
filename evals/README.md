# evals

The eval lane measures whether a real model does the work of a docket team well. It is a
development tool: outside the wheel, outside `testpaths`, and a real model never gates CI. The
contract is [specs/test-framework.md](../specs/test-framework.md) "Agent evals".

## A task is a directory

```text
evals/tasks/<suite>/<id>/
├── task.yaml    id, version, suite, shape, origin, instruction (<= 500 chars), pod, operator,
│                graders, limits
├── repo/        the seed repository the agent works in
├── hidden/      pytest checks the agent never sees; they read the repository through the
│                working directory and `EVAL_REPO`
└── solution/    a reference: one or more `*.patch` files, else a file tree copied over `repo/`
```

Graders are listed as `graders.required` (all must pass) and `graders.report` (shown only). An
entry is a name, or a one-key mapping when the grader takes params:

```yaml
graders:
  required:
    - outcome.hidden_tests
    - outcome.file_exact: {path: out.txt, content: "exact bytes\n"}
    - outcome.task_status: {status: done}
  report: [process.tokens]
```

A task that needs more than a repository says so in `task.yaml`: `pod.apply` (recipes or a directory
beside the task, installed with `docket pod update`), `pod.fetch_domains`, `pipeline`, `pod.memory`,
and `records`, the record sets exported after the run for `hidden/` to read through `EVAL_RECORDS`
(the reference rows are `solution-records/<set>.json`; `EVAL_SOLUTION_CHECK=1` tells a hidden check
it is judging a reference). An operator `approval: park` leaves the approval unanswered, for a task
whose right ending is `waiting_approval`. The `capability` suite uses all of them.

Any change to a task's content raises `version`; results of different versions are never mixed.
The loader (`evals/evaluator/task.py`) refuses a task that lacks a key, names an unknown grader or
breaks a bound, and it names the key.

## Check the reference solutions

```bash
uv run python -m evals.evaluator.run check-solutions            # every task
uv run python -m evals.evaluator.run check-solutions regression # one suite
uv run python -m evals.evaluator.run check-solutions basic      # one task
```

For each task the command copies `repo/` into a fresh `git init`, applies `solution/` and grades
each required `outcome.*` grader with no model: `outcome.hidden_tests` runs `hidden/` on a copy,
`outcome.file_exact` compares bytes. `outcome.task_status` needs a trial and is reported as
skipped; other grader kinds are not checked here. It exits 1 naming the first task and grader
that fails, or a selector that matches nothing, and prints the count of solutions that pass. CI
runs it on every push.

Tests of the evaluator itself are `evals/tests`: `uv run pytest evals/tests -q`.

## Run a model against the tasks

These spend model calls, so they never run in CI.

```bash
uv run python -m evals.evaluator.run run regression --provider NAME --model ID --epochs 3
uv run python -m evals.evaluator.run nightly --base <run dir or sha>
uv run python -m evals.evaluator.run compare --base <run dir or sha> --head <run dir>
```

`run` takes a suite name or a task id, registers the provider (`--base-url` and `--credential-env`
for a hosted or custom endpoint), runs each task for `--epochs` trials and writes `trials.jsonl`,
`summary.md` and `summary.json` under `evals-out/<utc stamp>/` (`--out` changes it). `nightly` is
`run regression` on the local endpoint (`http://127.0.0.1:8081/v1`) with three trials per task;
with `--base` it exits 1 naming a task that regressed. `compare` pairs a run with a base by
`task@version` and prints the difference; it exits 1 if a run is missing.

## Watch production, and turn a real failure into a task

```bash
uv run python -m evals.evaluator.run online-report --home ~/.docket           # last 7 days
uv run python -m evals.evaluator.run online-report --home ~/.docket --trend   # 7 days against the 28 before
uv run python -m evals.evaluator.run promote TASK_ID --pod POD --home ~/.docket
```

`online-report` reads a home and never writes it: pods through `docket status --all --json`, the
tasks from each pod's queue file. It prints success, reviewer rejection and rework by pod, role,
model id and prompt hash, each as `k/n` with its Wilson 95% interval. `--trend` marks a figure
`worse` or `better` only when the two intervals do not overlap, and says `not detectable` for
overlap or for fewer than 5 samples in a window. No prices appear. `promote` writes
`evals/tasks/candidates/<id>/` from a failed task: instruction, a `repo/` seed at the task's base
commit, a failing TODO check in `hidden/`, no `solution/`, secrets, home paths and user names
removed. A candidate is not a task: the loader refuses its suite until a person finishes it and moves
it into a real one.
