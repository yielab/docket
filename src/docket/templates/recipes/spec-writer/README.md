# spec-writer

**Practice:** test-driven implementation with inexpensive test authoring.

**Source idea:** write the tests first, from the brief alone, using an inexpensive model; then
implement against them using the normal model. Tests that fail on the base and pass on the
implementation are proof the implementation addresses the brief.

**What docket's gates make structural:** the write-tests step runs before the Implementer and
is briefed separately to write failing tests from the brief alone. The implementation step is
gated on `verify: true` (the Implementer's own verify command), so tests must pass to proceed.
`model: cheap` on the write-tests step reserves spend on the cheaper model for test scaffolding,
not implementation logic.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe spec-writer          # a new pod for the current repository
docket pod <project> apply spec-writer    # onto an existing pod
```

`pod.yaml` carries a `description` only (the recipe adds no new members or settings);
`apply` validates the pipeline before writing anything, and is safe to run again (a second
run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: spec-writer`, `description`.
- `pipeline.yaml` — `write-tests` (Implementer, `model: cheap`, custom instructions for test writing) -> `build` (Implementer, gated on its own verify command).

## Undo

```bash
docket pod <project> config unset pipeline
```
