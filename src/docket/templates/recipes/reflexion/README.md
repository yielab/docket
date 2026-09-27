# reflexion

**Practice:** Reflexion — bounded self-critique before verification.

**Source idea:** an agent's own output is critiqued and revised before it counts as final,
bounded so the critique-and-revise loop cannot run forever (Shinn et al., "Reflexion: Language
Agents with Verbal Reinforcement Learning").

**What docket's gates make structural:** `critique`'s `REQUEST-CHANGES` verdict is a real rework
edge back to `build`, bounded to two cycles by `maxCycles: 2` — not a suggestion an Implementer
can ignore, and not an unbounded loop either. The Tester's PASS/FAIL verdict runs only once the
Critic is satisfied, and is an independent gate from it.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe reflexion          # a new pod for the current repository
docket pod <project> apply reflexion    # onto an existing pod
```

`pod.yaml` names the two members this recipe adds (`critic`, `tester`); `apply` validates the
roster and `pipeline.yaml` before writing anything, and is safe to run again (a second run plans
every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: reflexion`, `members: [critic, tester]`.
- `pipeline.yaml` — `build` (Implementer, gated on its own verify command) -> `critique` (Critic,
  APPROVE/REQUEST-CHANGES verdict, rework -> build, maxCycles 2) -> `test` (Tester, PASS/FAIL
  verdict).

## Undo

```bash
docket pod <project> config unset pipeline
docket pod <project> remove <project>-critic
docket pod <project> remove <project>-tester
```
