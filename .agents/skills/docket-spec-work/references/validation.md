# Validation routing

Run the smallest useful check first, then the complete gates appropriate to the change.

| Surface | Focused evidence | Final evidence |
| --- | --- | --- |
| Python behavior | owning `tests/python/test_*.py` test | `uv run pytest` |
| Types/lint | changed module | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` |
| CLI text/shape | focused CLI pytest | `bash tests/golden/run.sh verify-all` |
| Spec | owning spec requirement/changelog | `bash scripts/validate-specs.sh` |
| README numeric claim | relevant local assertion | `uv run python scripts/metrics.py --check` |
| Packaging/dependency floor | wheel/import or focused package test | CI-equivalent floor check only when bounds/build change |
| Development harness | run helper with representative repo states | skill quick validation plus JSON/Python syntax checks |

Always use hermetic temporary state for product tests. No test may read or mutate the real Docket
home. Golden regeneration requires an intentional CLI contract change and a reviewed diff.
