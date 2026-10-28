# parallel-explore

Lead -> (Researcher A | Researcher B, in parallel) -> Implementer. The Lead splits the work
into two halves. Each Researcher runs on the cheap model class (`model: cheap` on its child
step) and maps one half. The `parallel` group joins before the Implementer edits with both
findings as its handoff. The Implementer's edit is gated on the pod's verify command
(`verify: true`); a failed gate sends the task back to the Lead once
(`on: {fail: {goto: lead, max: 1}}`).

The two Researcher instructions are disjoint by construction: each names one half of the
Lead's plan and its own paths.

## Apply it

For a new pod, or onto one that already has its `lead`:

```bash
docket init --recipe parallel-explore    # a new pod for the current directory
docket pod update parallel-explore       # onto an existing pod
```

`pod.yaml` names the two members this recipe adds: `researcher` and `implementer`. `apply`
validates the roster and `pipeline.yaml` before writing anything, and is safe to run again (a
second run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` - what `apply` reads: `members: [researcher, implementer]`.
- `pipeline.yaml` - `lead` (Lead) -> `explore` (parallel group: `map-a` and `map-b`, both
  Researchers on `model: cheap`) -> `build` (Implementer, gated on its verify command,
  fail -> lead, maxCycles 1).

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-implementer
```
