# Validation routing

Run the smallest useful check first, then the gates the change's surface needs. Rows are additive:
a Python CLI change that updates a spec takes the union of the Python, static, CLI and spec rows.
A test run costs wall time and context; spend it where it can change a decision.

| Surface | While iterating | Before handoff (the card's gate) |
| --- | --- | --- |
| Python behavior | the unit file whose `SUBJECT` is the module you changed (`rg -l 'SUBJECT = "docket.<module>"' tests`), then its context's integration file only if the step changed a seam | the card's named tests; the full suite is the integrator's, once per merge |
| Pure move or rename | none | `pytest --co -q` and `tests/architecture`; no new test |
| Comments / docstrings | — | `uv run python scripts/maint/comment_lint.py --check <touched files>` |
| Prose, artifacts, agent scripts | the one agent-lane file with `LANE`/`REASON`/`RETIRE_WHEN` | that file by path; the whole agent lane is phase-close |
| Types/lint | — | `uv run ruff check . && uv run ruff format --check . && uv run mypy src` |
| Tool output, wire, home layout, HTTP API | the card's focused test | `uv run pytest tests/e2e -n auto -q`, only when the card names it |
| CLI text/shape | focused CLI pytest | `bash tests/golden/run.sh verify-all`, `uv run python scripts/gen_cli_docs.py --check` |
| Spec | owning spec requirement and version | `bash scripts/validate-specs.sh` |
| Packaging/dependency floor | wheel/import or focused package test | CI-equivalent floor check only when bounds/build change |
| Development harness | run helper with representative repo states | skill quick validation plus JSON/Python syntax checks |
| Model provider/gateway | public key/preset path through recording HTTP fake | owning endpoint, driver, policy, auth, and compatibility tests |

## What a check costs (measured 2026-10-28)

16 cores, warm `uv`/mypy caches, `develop` at `392d26df`; 6,883 tests in the default suite. These
are working figures for choosing a check, not claims for README or ROADMAP.

| Check | Wall time | Who runs it, when |
| --- | --- | --- |
| `ruff check` + `ruff format --check` + `mypy src` (warm) + `pytest --co -q` | ~4 s | every commit; runs no test |
| `uv run pytest tests/architecture` | 3 s | every card before handoff |
| one unit file | ~1-3 s (each test's ceiling is 2 s) | while iterating, by path, under `timeout 120` |
| one integration file | most under 3 s | while iterating, only the one whose subject changed |
| default suite, `-n auto --dist loadfile` | 84 s | the integrator, once per merge; then failures by name |
| `tests/e2e -n auto` | 42 s | cards that change a tool's output, the wire, the home layout or the HTTP API |
| `tests/golden/run.sh verify-all` | 4 s | CLI text changes; phase close |
| `validate-specs.sh`, `gen_cli_docs.py --check`, `split_board.py check` | under 2 s each | spec or CLI changes; phase close |
| `tests/agent` (serial) | ~290 s | phase close only, on a **committed** tree: `test_adoption_evidence.py` refuses any uncommitted path |

The slowest files: run these only when your step changes their subject. Their cost is per-test
fixture setup, not assertions:

| File | Seconds |
| --- | --- |
| `tests/contracts/test_a2a_http.py` | 60 |
| `tests/contracts/test_escalation_http.py` | 35 |
| `tests/integration/operator/test_ntfy__email_delivery.py` | 13 |
| `tests/integration/interfaces/test_serve_tasks_endpoint.py` | 10 |
| `tests/integration/interfaces/test_serve_reattach.py`, `platform/test_fetch__wire.py`, `interfaces/test_serve_stop_signals.py`, `agent/test_sandboxed_exec.py` | 7-9 each |

Re-measure when a figure looks wrong or a lane's shape changes. Do it once, as the merge run, not
as an extra run:

```bash
uv run pytest -n auto --dist loadfile -q -p no:cacheprovider --durations=0 --durations-min=0.5 > d.txt
awk '/^[0-9.]+s (call|setup|teardown)/{sub(/s$/,"",$1);split($3,a,"::");f[a[1]]+=$1}
     END{for(k in f)printf "%6.1f %s\n",f[k],k}' d.txt | sort -rn | head
```

## Spending rules

- **One run answers one question.** Don't rerun a test that passed and whose subject has not
  changed since. Don't run the full suite "to make sure": a worker never runs it; the integrator
  runs it once per merge.
- **Output goes to a file.** Read the `FAILED` lines and the first traceback, never the whole log.
  The repository's `addopts` already pass `-q`, so a parallel run may print no summary line; check
  the exit code.
- **Stop rule.** A check that fails again after one fix stops the step: park with the failing line
  and a hypothesis. No third attempt and no polling loop.
- **Pre-existing failures** are proven in a clean worktree (`git worktree add`), never by stashing.

Always use hermetic temporary state for product tests. No test may read or mutate the real Docket
home or a tracked file (a store opened on a `tests/fixtures/` path drops a `.docket.lock` there: copy
the fixture to `tmp_path` first). Golden regeneration requires an intentional CLI contract change and
a reviewed diff.

Before implementation, record the relevant baseline and dirty paths. If a required gate fails, name
the command and first actionable failure, reproduce it against the baseline when practical, and
classify whether the change introduced it. Do not edit unrelated files to absorb a pre-existing
failure. A required gate that is not green remains missing evidence unless the owning contract has
an explicit waiver, so the handoff is `partial` even when the focused test passes.
