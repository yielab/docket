# Validation routing

Run the smallest useful check first, then the complete gates appropriate to the change. Rows are
additive: a Python CLI change that updates a spec takes the union of Python, static, CLI/golden, and
spec gates rather than selecting one row.

| Surface | Focused evidence | Final evidence |
| --- | --- | --- |
| Python behavior | owning `tests/python/test_*.py` test | `uv run pytest` |
| Types/lint | changed module | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` |
| CLI text/shape | focused CLI pytest | `bash tests/golden/run.sh verify-all` |
| Spec | owning spec requirement/changelog | `bash scripts/validate-specs.sh` |
| README numeric claim | relevant local assertion | `uv run python scripts/metrics.py --check` |
| Packaging/dependency floor | wheel/import or focused package test | CI-equivalent floor check only when bounds/build change |
| Development harness | run helper with representative repo states | skill quick validation plus JSON/Python syntax checks |
| Model provider/gateway | public key/preset path through recording HTTP fake | owning endpoint, driver, policy, auth, and compatibility tests |

Always use hermetic temporary state for product tests. No test may read or mutate the real Docket
home. Golden regeneration requires an intentional CLI contract change and a reviewed diff.

Before implementation, record the relevant baseline and dirty paths. If a required final gate fails,
name the command and first actionable failure, reproduce it against the baseline when practical, and
classify whether the change introduced it. Do not edit unrelated files to absorb a pre-existing
failure. A required gate that is not green remains missing evidence unless the owning contract has
an explicit waiver, so the handoff is `partial` even when the focused test passes.
