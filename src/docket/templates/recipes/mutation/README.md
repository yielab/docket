# mutation

**Practice:** mutation testing -- a test suite is only as good as the share of deliberate bugs it
catches.

**Tool:** [mutmut](https://pypi.org/project/mutmut/) 3.x, which **must be installed** where
docket runs (`pip install mutmut`). If it is not on `PATH` the step fails with that message; it
never silently passes.

**What docket's gates make structural:** after the Implementer's verify gate, `check-mutation-score`
is a `run` command step. It reads `DOCKET_BASE_COMMIT` and `DOCKET_HEAD_COMMIT`, lists the Python
source files added or modified between them (test files and `__init__.py` are excluded), runs
`mutmut run <module>.*` for those modules, reads `mutants/mutmut-cicd-stats.json` from
`mutmut export-cicd-stats`, and fails the task when killed / (killed + survived + timeout +
suspicious + no_tests + segfault) is below the threshold (80 percent by default). No changed source
file, or no mutants produced, passes with a message. The `mutants/` directory is removed afterwards
unless it already existed.

## Apply it

```bash
docket init --recipe mutation          # a new pod
docket pod apply mutation    # onto an existing pod
```

## Commands the step runs

The step's command is a single `python3 -c '...'`. docket classifies only that line: `python3` is
on the curated allowlist, so the verdict is `allow` and no `allowCommands` entry is needed. The
script then runs, unclassified, as subprocesses: `git diff --name-only --diff-filter=AM`, then
`mutmut run <modules>` and `mutmut export-cicd-stats`.

## Scope is by file, not by line

mutmut 3 cannot be restricted to changed lines, and has no path flag: it mutates by module name.
The step passes the changed files as module-name globs (`src/pkg/calc.py` becomes `pkg.calc.*`),
so every function in a changed file is mutated, not only the lines the task touched. A leading
`src/` or `lib/` is stripped; mutmut must be able to locate the code (a `src/` or `lib/` directory,
or a package directory named like the repository, otherwise set `source_paths` in `pyproject.toml`
or `setup.cfg`). Python only.

## Customise

The step declares `MUTATION_THRESHOLD` (percent, default `80`) and `MUTATION_CMD` (default
`mutmut`) under its own `env:`. A pod overrides them by editing the step: `docket pod <project>
export <dir>`, change the `env:` values in `<dir>/pipeline.yaml`, then `docket pod apply
<dir>`. For anything else edit the script in `pipeline.yaml`. The step has a 900 second timeout.

## Undo

```bash
docket pod <project> config unset pipeline
```
