# frugal

**Practice:** cost-bounded dispatch — a spend cap plus cheap-tier planning and review.

**Source idea:** most planning and review turns don't need the strongest, most expensive model —
reserve spend for the step that actually needs it (the Implementer) and cap the rest, the
right-size-the-model-to-the-role practice model-routing setups use.

**What docket's gates make structural:** `budgetUsd: 2` is enforced by dispatch's own budget
gate — a task that would exceed it pauses rather than silently overspending. The pipeline's own
`on: {REQUEST-CHANGES: {goto: build, max: 1}}` bounds the Reviewer's rework edge. `model: cheap` on `plan` and `review` resolves
against the live rank anchors for that hop only; it is never persisted to the Lead's or
Reviewer's own model, so removing this pipeline restores their ordinary resolution.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe frugal          # a new pod for the current repository
docket pod update frugal    # onto an existing pod
```

`pod.yaml` names the one member this recipe adds (`reviewer`) and the two settings it writes
(`budgetUsd`, `turnTimeoutS`); `apply` validates the roster, the settings and
`pipeline.yaml` before writing anything, and is safe to run again (a second run plans every item
`skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: frugal`, `members: [reviewer]`,
  `settings: {budgetUsd: 2, turnTimeoutS: 600}`.
- `pipeline.yaml` — `plan` (Lead, `model: cheap`) -> `build` (Implementer, gated on its own
  verify command) -> `review` (Reviewer, `model: cheap`, APPROVE/REQUEST-CHANGES verdict, rework
  -> build, maxCycles 1).

## Undo

```bash
docket pod unset pipeline
docket pod unset budgetUsd
docket pod unset turnTimeoutS
docket pod remove <project>-reviewer
```
