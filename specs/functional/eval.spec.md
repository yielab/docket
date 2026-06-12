# Eval Harness Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-13

## Purpose

This specification defines the specialist-role eval harness — golden-task checks that
measure whether each specialist role performs adequately on its configured model — and
the `rack eval` command that runs it. Stored results feed per-role model right-sizing
hints (shown by `rack eval --recommend` and `rack doctor`), the data source for tuning
the role→model policy (see model-profiles.spec.md).

## Scope

This specification covers:

- Running evals (`rack eval`, structural and live modes)
- Per-role selection and the recorded results format
- Right-sizing hints derived from stored results

This specification does NOT cover the role→model policy itself (see
model-profiles.spec.md) or the unit/integration test suites.

## Requirements

### Running evals (rack eval)

1. One eval script per specialist role **MUST** exist under `tests/evals/`
   (`<role>.eval.sh` for programmer, reviewer, tester, knowledge, security, manager).
2. `rack eval` **MUST** run all role evals in structural mode by default: checks that
   do not call a model (workspace/template shape) and that skip rather than fail when
   prerequisites are absent.
3. `rack eval --live` (or `RACK_EVAL_LIVE=1`) **MUST** enable live golden-task checks
   that exercise the agent's actual model; infrastructure failures (quota, network)
   **MUST** report as SKIP, not FAIL.
4. `rack eval --role <r>` **MUST** run only that role's eval and **MUST** error with
   the list of available roles when no such eval exists.
5. `--tier <economy|standard|premium>` **MUST** set the model-class label recorded with
   results (the internal rank classes; default `standard`). It labels which class the
   eval ran under; it does not change any agent's model.
6. Evals **MUST** be non-blocking for CI: a SKIP outcome (role not installed, live mode
   off) **MUST NOT** fail the run.

### Results and right-sizing hints

1. Live runs **MUST** append one JSON line per role run to
   `tests/evals/results/YYYY-MM-DD.jsonl` recording at least `date`, `role`, `tier`
   (model-class label), `passed`, and `costUsd`.
2. `rack eval --recommend` **MUST** read the most recent results file and print one
   hint per role: if the role passed on a cheaper model class than its current one,
   suggest changing the role's model (`rack models set <role> <provider/model>`);
   otherwise report the minimum passing class. It **MUST** run no evals.
3. `rack doctor` **MUST** surface the same hints when results exist, advisory only
   (no issue-count bump).

## Interface Contracts

### CLI Command Signatures

```bash
rack eval                          # All roles, structural mode
rack eval --live                   # Enable live golden-task checks
rack eval --role <role>            # One role only
rack eval --tier <class>           # Model-class label for recorded results
rack eval --recommend              # Right-sizing hints from stored results
```

### Result Record Schema (one JSON object per line)

```json
{"date": "2026-06-13", "role": "reviewer", "tier": "economy",
 "passed": true, "costUsd": 0.0042}
```

### Return Codes

- `0`: PASS (or all skipped)
- `2`: SKIP (agent not installed / live mode off, single-role form)
- other non-zero: FAIL

## Examples

### Structural run and a live single-role run

```bash
$ rack eval
  SKIP  knowledge
  SKIP  manager
  ...
  Pass: 0   Skip: 6   Fail: 0

$ rack eval --live --role reviewer --tier economy
✓ PASS — reviewer
```

### Right-sizing hints

```bash
$ rack eval --recommend
  reviewer: passes on a cheaper model class (economy, avg $0.0042/run) — rack models set reviewer <provider/model>
  programmer: standard is the minimum passing model class (avg $0.0310/run)
```

## Validation

### Pre-conditions

- `tests/evals/run-evals.sh` and the per-role eval scripts **MUST** be present.

### Post-conditions

- A live run appends one result record per role executed.
- `--recommend` leaves the results files unmodified.

### Invariants

- Structural mode never calls a model and never spends tokens.
- A SKIP is never reported as a FAIL.
- Hints reference roles and models, never instruct per-agent tier changes.

## Changelog

### Version 1.0.0 (2026-06-13)

- Initial eval-harness specification (structural/live modes, results JSONL,
  right-sizing hints); documents behavior shipped in Phase 5, hint phrasing
  aligned with the Phase 6b role→model policy
