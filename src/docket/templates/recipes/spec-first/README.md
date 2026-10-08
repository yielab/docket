# spec-first

**Practice:** specification-first (spec-driven) development.

**Source idea:** write the specification and get it approved before any implementation exists,
so a design mistake is caught on paper rather than in a diff.

**What docket's gates make structural:** `approve-spec` is a real verdict gate — a Critic's
`REJECT` sends the task back to `spec` (bounded to one rework cycle), and `build` cannot run
until that gate passes `APPROVE`. The Reviewer's own `APPROVE`/`REQUEST-CHANGES` gate after
`build` is a separate, independent gate: an approved spec does not itself excuse a bad diff.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe spec-first          # a new pod for the current repository
docket pod apply spec-first    # onto an existing pod
```

`pod.yaml` names the three members this recipe adds (`writer`, `critic`, `reviewer`); `apply`
validates the roster and `pipeline.yaml` before writing anything, and is safe to run again (a
second run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: spec-first`, `members: [writer, critic,
  reviewer]`.
- `pipeline.yaml` — `spec` (Writer drafts the specification) -> `approve-spec` (Critic,
  APPROVE/REJECT verdict, rework -> spec, maxCycles 1) -> `build` (Implementer, gated on its own
  verify command) -> `review` (Reviewer, APPROVE/REQUEST-CHANGES verdict, rework -> build,
  maxCycles 1).
- `skills/writing-a-spec/SKILL.md` -- the shape of a spec a Critic can approve and an Implementer can build from; listed in the prompt, read on demand with the `skill` tool.

## Undo

```bash
docket pod <project> config unset pipeline
docket pod <project> remove <project>-writer
docket pod <project> remove <project>-critic
docket pod <project> remove <project>-reviewer
```
