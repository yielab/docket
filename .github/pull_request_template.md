## Summary

<!-- What does this PR do? One sentence. -->

## Changes

<!-- Bullet list of concrete changes -->

## Test plan

- [ ] `uv run pytest` passes
- [ ] `bash tests/golden/run.sh verify-all` passes (recapture goldens if output changed intentionally)
- [ ] `uv run ruff check . && uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `bash scripts/validate-specs.sh`, `uv run python scripts/metrics.py --check` and `uv run python scripts/gen_cli_docs.py --check` pass (`docs/commands.md` is generated — never hand-edit it)
- [ ] `uv run python scripts/maint/comment_lint.py --check` clean on touched files
- [ ] Manually tested: `docket <command>` with the affected path

## Checklist

- [ ] Model choices follow the role→model policy (no hardcoded models; tier names economy/standard/premium are not accepted as user-facing values, removed in 0.2.0)
- [ ] All docket-owned JSON I/O goes through `edges/store.py` (atomic + filelock + 0600)
- [ ] Any new tool handler is dispatched only through `core/tools.py`'s single chokepoint (an AST test enforces this — no second execution path)
- [ ] Mutating operations emit an audit entry (`core/audit.py`)
- [ ] New read commands expose a `--json` flag with a shape documented in `specs/data/cli-json-shapes.spec.md`
- [ ] Spec-first: behaviour is specified under `specs/` (validated by `./scripts/validate-specs.sh`)
