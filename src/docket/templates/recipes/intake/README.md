# intake

**Practice:** structured intake / requirements triage before implementation starts.

**Source idea:** an operator who assigns work and walks away benefits most when the Lead
reasons about the task *before* handing it to the Implementer -- naming what "done" means,
what it needs, and what it doesn't know yet -- rather than guessing silently or blocking on
every risky action.

**What docket's gates make structural:** the Lead's first hop ends in exactly one marker.
`READY` only reaches the Implementer after `_check_brief_resources` confirms every
`secret:`/`path:`/`verify` resource the brief named is actually present -- a missing one
blocks the task (`blockedReason: resources`, `AUTH_REQUIRED` in the A2A view) instead of
letting the Implementer discover it mid-turn. `NEEDS-INPUT` turns the brief's own
`questions` into a real operator question (one property per question, not a single
free-text box) and returns to the Lead once they're answered. `REJECT` fails the task
immediately (`failureKind: rejected`, `REJECTED` in the A2A view) instead of consuming an
Implementer turn on a task the Lead has already decided not to attempt. The brief is
optional: a reply with no parseable brief but a `READY` marker still advances exactly as
before this recipe existed.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe intake          # a new pod for the current repository
docket pod apply intake    # onto an existing pod
```

`pod.yaml` names the one member this recipe adds beyond the lean pod (`reviewer`); `apply`
validates the roster and `pipeline.yaml` before writing anything, and is safe to run again
(a second run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` -- what `apply` reads: `kind: pod`, `name: intake`, `members: [reviewer]`.
- `pipeline.yaml` -- `lead` (writes a typed brief, `READY`/`NEEDS-INPUT`/`REJECT`) ->
  `ask` (an operator-input step, only reached on `NEEDS-INPUT`, loops back to `lead` once
  answered, capped) -> `build` (Implementer, gated on its own verify command) -> `review`
  (Reviewer, APPROVE/REQUEST-CHANGES verdict, rework -> build, maxCycles 1).

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-reviewer
```
