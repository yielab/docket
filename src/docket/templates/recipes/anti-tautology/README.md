# anti-tautology

**Practice:** a test is only evidence if it can fail. A test that already passes on the code from
before the task does not test the task.

**What docket's gates make structural:** after the Implementer's verify gate, `check-tests-fail-on-base`
is a `run` command step. It reads `DOCKET_BASE_COMMIT` and `DOCKET_HEAD_COMMIT` (set for command
steps), lists test files added or modified between them, creates a disposable detached worktree
at the base commit, copies those files in as committed at the head, and runs them there. If they
pass (or collect no tests) on the base, the step fails and so does the task. If they fail on the
base, the step passes. If no test file changed, it passes with a message. The worktree is always
removed afterwards. Any failure on the base counts, including an import error for code the task
adds.

## Apply it

```bash
docket init --recipe anti-tautology          # a new pod
docket pod <project> apply anti-tautology    # onto an existing pod
```

## Commands the step runs

The step's command is a single `python3 -c '...'`. docket classifies only that line: `python3` is
on the curated allowlist and the script avoids `${`, `$(`, backticks, `eval ` and `exec `, so the
verdict is `allow` and no `allowCommands` entry is needed. The script itself then runs, as
subprocesses that the classifier never sees: `git diff --name-only --diff-filter=AM`,
`git worktree add --detach`, `git show <head>:<file>`, `git worktree remove --force`, and the test
runner (default `python3 -m pytest -q <files>`).

## Customise

The command carries no `${var}` interpolation (pipeline `run` has none), so two environment
variables of the process that runs `docket` override the defaults:

- `ANTI_TAUTOLOGY_GLOB` -- comma-separated file-name globs, default `test_*.py,*_test.py`
- `ANTI_TAUTOLOGY_RUNNER` -- the runner command, default `python3 -m pytest -q`

For anything else, edit the script in `pipeline.yaml`.

## Limits

Only files are compared, not individual test functions: a changed file that mixes a new failing
test with old passing ones passes the check only if the file as a whole fails on the base.

## Undo

```bash
docket pod <project> config unset pipeline
```
