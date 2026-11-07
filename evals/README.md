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

Any change to a task's content raises `version`; results of different versions are never mixed.
The loader (`evals/harness/task.py`) refuses a task that lacks a key, names an unknown grader or
breaks a bound, and it names the key.

## Check the reference solutions

```bash
uv run python -m evals.harness.run check-solutions            # every task
uv run python -m evals.harness.run check-solutions regression # one suite
uv run python -m evals.harness.run check-solutions fix-add    # one task
```

For each task the command copies `repo/` into a fresh `git init`, applies `solution/` and grades
each required `outcome.*` grader with no model: `outcome.hidden_tests` runs `hidden/` on a copy,
`outcome.file_exact` compares bytes. `outcome.task_status` needs a trial and is reported as
skipped; other grader kinds are not checked here. It exits 1 naming the first task and grader
that fails, and 0 when there is nothing to check. CI runs it on every push.

Tests of the harness itself are `evals/tests`: `uv run pytest evals/tests -q`.
