# cross-family-review

**Practice:** a reviewer from another provider family.

**Source idea:** a reviewer from the same model family tends to share the implementer's blind
spots. Here the Implementer runs on Anthropic and the Reviewer on OpenAI.

**What docket's gates make structural:** `model: anthropic/claude-sonnet-4-6` on `build` and
`model: openai/gpt-4.1-mini` on `review` pin the two families, whatever the pod's default or any
`docket setup model set` pin.
The Reviewer's APPROVE/REQUEST-CHANGES verdict is a bounded rework edge: a REQUEST-CHANGES
sends the task back to the Implementer (limited to one cycle) before the task is done.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe cross-family-review          # a new pod for the current repository
docket pod <project> apply cross-family-review    # onto an existing pod
```

Set both providers' credentials first: `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, as
environment variables or in `secrets.json`.

`pod.yaml` names the one member this recipe adds (`reviewer`); `apply` validates the roster
and pipeline before writing anything, and is safe to run again (a second run plans every item
`skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: cross-family-review`, `members: [reviewer]`, `description`.
- `pipeline.yaml` — `build` (Implementer, `model: anthropic/claude-sonnet-4-6`, gated on its own verify command) -> `review` (Reviewer, `model: openai/gpt-4.1-mini`, APPROVE/REQUEST-CHANGES verdict, rework -> build, maxCycles 1).

## Undo

```bash
docket pod <project> config unset pipeline
docket pod <project> remove <project>-reviewer
```
