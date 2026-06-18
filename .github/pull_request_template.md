## Summary

<!-- What does this PR do? One sentence. -->

## Changes

<!-- Bullet list of concrete changes -->

## Test plan

- [ ] `./tests/unit/test-helpers.sh` passes (all N tests green)
- [ ] `./tests/test-lifecycle.sh` passes (or explain why not run)
- [ ] Manually tested: `docket <command>` with the affected path

## Checklist

- [ ] No hardcoded model names (use `economy`/`standard`/`premium` tier language in templates)
- [ ] JSON writes go through `json_atomic_write` + `with_docket_lock`
- [ ] Mutating ops emit an `docket_audit` line
- [ ] New commands have a `--json` flag if they read structured data
- [ ] `bash -n lib/commands/<file>.sh` passes (no syntax errors)
