# cross-family-review

**Practice:** cross-provider veto on diffs — different models from different vendors.

**Source idea:** get a second opinion on the code from a model trained on a different dataset
and architecture. The Implementer uses the default model (typically Anthropic), while the
Reviewer sees it with an independent model (here, OpenAI), so each is blind to the other's
training biases.

**What docket's gates make structural:** `model: openai/gpt-4.1-mini` on the `review` step
ensures the Reviewer runs on OpenAI regardless of the default or any `docket models set` pin.
The Reviewer's APPROVE/REQUEST-CHANGES verdict is a bounded rework edge: a REQUEST-CHANGES
sends the task back to the Implementer (limited to one cycle) before the task is done.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe cross-family-review          # a new pod for the current repository
docket pod <project> apply cross-family-review    # onto an existing pod
```

Before applying, ensure you have both Anthropic and OpenAI credentials configured:

```bash
docket auth set anthropic $ANTHROPIC_API_KEY
docket auth set openai $OPENAI_API_KEY
```

`pod.yaml` names the one member this recipe adds (`reviewer`); `apply` validates the roster
and pipeline before writing anything, and is safe to run again (a second run plans every item
`skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: cross-family-review`, `members: [reviewer]`, `description`.
- `pipeline.yaml` — `build` (Implementer, gated on its own verify command) -> `review` (Reviewer, `model: openai/gpt-4.1-mini`, APPROVE/REQUEST-CHANGES verdict, rework -> build, maxCycles 1).

## Undo

```bash
docket pod <project> config unset pipeline
docket pod <project> remove <project>-reviewer
```
