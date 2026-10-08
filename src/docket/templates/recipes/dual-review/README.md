# dual-review

**Practice:** dual (independent) review — two reviewers, no cross-talk.

**Source idea:** two independent reviewers catch more than one, and reviewing concurrently
without seeing each other's verdict avoids one anchoring on the other — the same rationale
behind requiring two approvals on a pull request.

**What docket's gates make structural:** `reviews` is a real `parallel` group — the Reviewer and
the Critic run as two independent, concurrently-dispatched agent turns, each gated on its own
role's own verdict contract (Reviewer's `APPROVE`/`REQUEST-CHANGES`, Critic's `APPROVE`/`REJECT`),
neither seeing the other's output before its own turn completes. The group's outcome is a
priority merge — any child failing fails the whole group — so a "quiet" reviewer cannot let a
change through on the other's approval alone.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe dual-review          # a new pod for the current repository
docket pod apply dual-review    # onto an existing pod
```

`pod.yaml` names the two members this recipe adds (`reviewer`, `critic`); `apply` validates the
roster and `pipeline.yaml` before writing anything, and is safe to run again (a second run plans
every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: dual-review`, `members: [reviewer,
  critic]`.
- `pipeline.yaml` — `build` (Implementer, gated on its own verify command) -> `reviews`, a
  `parallel` group of `review-code` (Reviewer) and `review-risk` (Critic), each falling back to
  its own role's default verdict gate since neither step declares one explicitly.

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-reviewer
docket pod remove <project>-critic
```
