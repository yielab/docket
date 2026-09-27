# research-review

Lead -> Researcher -> Analyst -> Writer -> Critic, gated on the Critic's APPROVE/REJECT
verdict with one bounded rework cycle back to the Writer. `researcher`, `analyst`, `writer`
and `critic` are all built-in starter archetypes (`docket roles list`) — no role YAML to add,
just roster and pipeline.

This is the same pipeline shape as the built-in `research` pod blueprint
(`docket init --blueprint research`). Use this recipe instead when you want the same
review discipline on a pod that already exists and was not created with that blueprint.

## Apply it

For a new pod, or onto one that already exists:

```bash
docket init --recipe research-review          # a new pod for the current directory
docket pod <project> apply research-review    # onto an existing pod
```

`pod.yaml` names the four built-in-archetype members this recipe adds; `apply` validates the
resulting roster and `pipeline.yaml` before writing anything, and is safe to run again (a
second run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `members: [researcher, analyst, writer, critic]`.
- `pipeline.yaml` — `lead -> researcher -> analyst -> writer -> critic (verdict gate,
  rework -> writer, maxCycles 1)`.

## Undo

```bash
docket pod <project> config unset pipeline
```
