# strong-plan-cheap-edit

Lead -> Implementer. The Lead plans on the strong model class (`model: strong` on its step)
and the Implementer edits on the cheap model class (`model: cheap` on its step). The edit is
gated on the pod's verify command (`verify: true`). A failed gate sends the task back to the
Implementer once (`on: {fail: {goto: build, max: 1}}`).

The pod's `verifyCmd` setting supplies the command the gate runs; this recipe does not set it.

## Apply it

For a new pod, or onto one that already has its `lead`:

```bash
docket init --recipe strong-plan-cheap-edit    # a new pod for the current directory
docket pod update strong-plan-cheap-edit       # onto an existing pod
```

`pod.yaml` names the one member this recipe adds: `implementer`. `apply` validates the roster
and `pipeline.yaml` before writing anything, and is safe to run again (a second run plans every
item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` - what `apply` reads: `members: [implementer]`.
- `pipeline.yaml` - `plan` (Lead, `model: strong`) -> `build` (Implementer, `model: cheap`,
  gated on its verify command, fail -> build, maxCycles 1).

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-implementer
```
