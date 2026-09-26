# ops-approval

Gate an Operator's action behind an explicit human sign-off: the approval gate stops the run
*before* the Operator's own turn, not after, so nothing runs unattended. `operator` is a
built-in starter archetype (`docket roles list`) — no role YAML to add.

This is narrower than the built-in `ops` pod blueprint (`docket init --blueprint ops`, which
also provisions a Monitor and requires choosing that blueprint at pod creation). Use this
recipe when you want the same human-in-the-loop discipline on a pod that already exists.

## Apply it

Against an existing pod `<project>`:

```bash
docket pod <project> add operator

docket pipeline validate pipeline.yaml
docket pipeline plan <project> --file pipeline.yaml   # confirm nothing is skipped
docket pod <project> config set pipeline pipeline.yaml
```

Answer the resulting approval with `docket approve <token>` / `docket deny <token>` (also
reachable over HTTP, MCP or Telegram `/approve` — every channel is audited). Unanswered
requests are denied after `APPROVAL_TIMEOUT` (900s).

Optional: copy the policy pack so a deploy/production-shaped operator command always asks a
human too, independent of which pipeline step it reached:

```bash
docket policies validate policies/ops-approval-high-risk.json
cp policies/ops-approval-high-risk.json ~/.docket/policies/
```

## Files

- `pipeline.yaml` — `lead (assess) -> operator (act, approval gate)`.
- `policies/ops-approval-high-risk.json` — optional; requires approval for deploy/production
  shaped commands from the operator role.

## Undo

```bash
docket pod <project> config unset pipeline
rm ~/.docket/policies/ops-approval-high-risk.json   # if copied
```
