# research-review

Lead -> Researcher -> Analyst -> Writer -> Critic, gated on the Critic's APPROVE/REJECT
verdict with one bounded rework cycle back to the Writer. `researcher`, `analyst`, `writer`
and `critic` are all built-in starter archetypes (`docket roles list`) — no role YAML to add,
just roster and pipeline.

This is the same pipeline shape as the built-in `research` pod blueprint
(`docket init --blueprint research`). Use this recipe instead when you want the same
review discipline on a pod that already exists and was not created with that blueprint.

## Apply it

Against an existing pod `<project>`:

```bash
docket pod <project> add researcher
docket pod <project> add analyst
docket pod <project> add writer
docket pod <project> add critic

docket pipeline validate pipeline.yaml
docket pipeline plan <project> --file pipeline.yaml   # confirm nothing is skipped
docket pod <project> config set pipeline pipeline.yaml
```

## Files

- `pipeline.yaml` — `lead -> researcher -> analyst -> writer -> critic (verdict gate,
  rework -> writer, maxCycles 1)`.

## Undo

```bash
docket pod <project> config unset pipeline
```
