# Real-world product tests

Read this when the affected contract needs a realistic fixture or boundary matrix.

For each behavior under test, record:

- supported initial state and the nearest invalid or legacy state;
- the public/default entry point and exact input shape;
- observable return, exit, or wire result;
- persisted state and forbidden extra side effects;
- the oracle that would fail on the previous behavior.

Use temporary Docket home and repository state. Prefer the real parser, caller, dispatcher, reader,
and writer with deterministic fakes only at network/process/model boundaries. For behavior changes,
run the new focused test before implementation and confirm its failure identifies the behavior
rather than fixture setup. For documentation-only work, verify the existing behavior and add a test
only if the claim lacks coverage. A test that only invokes a helper cannot prove a public capability.

Select only risks exposed by the contract. Useful dimensions include equivalent CLI argv shapes,
supported persisted versions and atomic migration failure, retries/idempotency, concurrent writers,
packaging floors, and required-gate failure. Assert exact semantic state, not complete log wording.

Skill maintainers performing an independent behavioral evaluation use `forward-tests.md` as the
hidden post-run rubric. Do not give that file to the evaluated agent.
