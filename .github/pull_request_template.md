## Summary

<!-- What does this PR do? One sentence. -->

## Changes

<!-- Bullet list of concrete changes -->

## Test plan

- [ ] `uv run pytest` passes
- [ ] `bash tests/golden/run.sh verify-all` passes (recapture goldens if output changed intentionally)
- [ ] `uv run ruff check . && uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] Manually tested: `docket <command>` with the affected path

## Checklist

- [ ] Model choices follow the role→model policy (no hardcoded models; tier names economy/standard/premium are deprecated)
- [ ] All docket-owned JSON I/O goes through `edges/store.py` (atomic + filelock + 0600)
- [ ] Any `openclaw.json` / auth-profile / provider access goes through the ACL (`edges/adapters/openclaw.py`) — no other module touches those formats
- [ ] Mutating operations emit an audit entry (`core/audit.py`)
- [ ] New read commands expose a `--json` flag with a shape documented in `specs/data/cli-json-shapes.spec.md`
- [ ] Spec-first: behaviour is specified under `specs/` (validated by `./scripts/validate-specs.sh`)
