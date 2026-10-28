# explore-then-edit

Researcher -> Implementer -> Reviewer. The Researcher runs on the cheap model class
(`model: cheap` on its step, overriding the built-in `researcher` archetype's `strong`) and
maps the code the task touches. The Implementer edits with that map as its handoff, and the
Reviewer's APPROVE/REQUEST-CHANGES verdict is the last gate, with one rework cycle back to the
Implementer.

## Apply it

For a new pod, or onto one that already exists:

```bash
docket init --recipe explore-then-edit    # a new pod for the current directory
docket pod update explore-then-edit       # onto an existing pod
```

`pod.yaml` names the three members this recipe adds: `researcher`, `implementer` and
`reviewer`. `apply` validates the roster and `pipeline.yaml` before writing anything, and is
safe to run again (a second run plans every item `skip`). `--dry-run` prints the plan without
writing.

## Files

- `pod.yaml` - what `apply` reads: `members: [researcher, implementer, reviewer]`.
- `pipeline.yaml` - `explore` (Researcher, `model: cheap`) -> `build` (Implementer) ->
  `review` (Reviewer, APPROVE/REQUEST-CHANGES verdict, rework -> build, maxCycles 1).

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-implementer
docket pod remove <project>-reviewer
```
