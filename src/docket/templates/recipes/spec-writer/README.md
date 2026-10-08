# spec-writer

**Practice:** test-driven implementation where a different model writes the tests.

**Source idea:** write the tests first, from the brief alone, with one model; then implement
against them with another. A model that writes both the tests and the code can make them agree
with each other instead of with the brief.

**What docket's gates make structural:** the write-tests step runs before the Implementer and
is briefed separately to write failing tests from the brief alone. The implementation step is
gated on `verify: true` (the Implementer's own verify command), so tests must pass to proceed.
The two steps pin different models (`openai/gpt-4.1-mini` writes the tests,
`anthropic/claude-sonnet-4-6` implements), whatever the pod's default or any `docket setup model set`
pin. Set `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` (environment or `secrets.json`) first. To check
that the new tests really fail on the base, add the `anti-tautology` recipe's step.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe spec-writer          # a new pod for the current repository
docket pod apply spec-writer    # onto an existing pod
```

`pod.yaml` carries a `description` only (the recipe adds no new members or settings);
`apply` validates the pipeline before writing anything, and is safe to run again (a second
run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: spec-writer`, `description`.
- `pipeline.yaml` — `write-tests` (Implementer role, `model: openai/gpt-4.1-mini`, test-writing instructions) -> `build` (Implementer, `model: anthropic/claude-sonnet-4-6`, gated on its own verify command).

## Undo

```bash
docket pod unset pipeline
```
