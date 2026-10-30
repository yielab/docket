# reflexion

**Practice:** Reflexion — bounded self-critique before verification.

**Source idea:** an agent's own output is critiqued and revised before it counts as final,
bounded so the critique-and-revise loop cannot run forever (Shinn et al., "Reflexion: Language
Agents with Verbal Reinforcement Learning").

**What docket's gates make structural:** `critique`'s `REQUEST-CHANGES` verdict is a real rework
edge back to `build`, bounded to two cycles by `maxCycles: 2` — not a suggestion an Implementer
can ignore, and not an unbounded loop either. The pipeline ends at the Reviewer's `APPROVE`; the Implementer's own verify command is the
gate that runs the suite.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe reflexion          # a new pod for the current repository
docket pod update reflexion    # onto an existing pod
```

`pod.yaml` names the one member this recipe adds (`reviewer`); `apply` validates the
roster and `pipeline.yaml` before writing anything, and is safe to run again (a second run plans
every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: reflexion`, `members: [reviewer]`.
- `pipeline.yaml` — `build` (Implementer, gated on its own verify command) -> `critique` (Reviewer,
  APPROVE/REQUEST-CHANGES verdict, rework -> build, maxCycles 2).

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-reviewer
```
