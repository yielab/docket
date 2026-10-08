# ops-approval

Gate an Operator's action behind an explicit human sign-off: the approval gate stops the run
*before* the Operator's own turn, not after, so nothing runs unattended. `operator` is a
built-in starter archetype (`docket pod roles`) — no role YAML to add.

This is narrower than the built-in `ops` pod blueprint (`docket init --blueprint ops`, which
also provisions a Monitor and requires choosing that blueprint at pod creation). Use this
recipe when you want the same human-in-the-loop discipline on a pod that already exists.

## Apply it

For a new pod, or onto one that already exists:

```bash
docket init --recipe ops-approval          # a new pod for the current directory
docket pod apply ops-approval    # onto an existing pod
```

`pod.yaml` names the one member this recipe adds (`operator`); `apply` validates the policy
pack, the resulting roster and `pipeline.yaml` before writing anything, and is safe to run again
(a second run plans every item `skip`). `--dry-run` prints the plan without writing. The bundled
`policies/ops-approval-high-risk.yaml` is applied along with everything else, so a
deploy/production-shaped operator command always asks a human too, independent of which
pipeline step it reached.

Answer the resulting approval with `docket approve <token>` / `docket deny <token>` (also
reachable over HTTP, MCP or Telegram `/approve` — every channel is audited). Unanswered
requests are denied after `APPROVAL_TIMEOUT` (900s).

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: ops-approval`, `members: [operator]`.
- `pipeline.yaml` — `lead (assess) -> operator (act, approval gate)`.
- `policies/ops-approval-high-risk.yaml` — applied into the pod's own policy directory; gained a
  structured `tool: bash` predicate alongside its `matches` (Phase 31, D-47), so it only
  evaluates the regex against an actual shell command rather than every `pre_tool_call` hook's
  rendered text; still requires approval for deploy/production shaped commands from the operator
  role.

## Undo

```bash
docket pod <project> config unset pipeline
rm ~/.docket/workspaces/pods/<project>/config/policies/ops-approval-high-risk.yaml
```
