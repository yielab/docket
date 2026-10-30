# research-review

Lead -> Researcher -> Analyst -> Writer -> Reviewer, gated on the Reviewer's APPROVE/REQUEST-CHANGES
verdict with one bounded rework cycle back to the Writer. `researcher`, `analyst`, `writer`
are starter archetypes and `reviewer` is a built-in one (`docket pod roles`) — no role YAML to add,
just roster and pipeline.

It is close to the built-in `respond` pod blueprint's research, draft and review steps, without
the Actor. Use this recipe when you want that review discipline on a pod that already exists.

## Apply it

For a new pod, or onto one that already exists:

```bash
docket init --recipe research-review          # a new pod for the current directory
docket pod update research-review    # onto an existing pod
```

`pod.yaml` names the four built-in-archetype members this recipe adds; `apply` validates the
resulting roster and `pipeline.yaml` before writing anything, and is safe to run again (a
second run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `members: [researcher, analyst, writer, reviewer]`.
- `pipeline.yaml` — `lead -> researcher -> analyst -> writer -> reviewer (verdict gate,
  rework -> writer, maxCycles 1)`.

## Undo

```bash
docket pod unset pipeline
```
