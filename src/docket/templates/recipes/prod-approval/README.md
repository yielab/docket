# prod-approval

A policy pack: one guardrail policy, no roles, no pipeline, no members.

**Threat model, in three sentences.** `ops-approval` gates the Operator role, but a pod's
Implementer can run the exact same deploy commands through `bash` on the way to "done", and the
Implementer has no approval gate of its own in most pipelines. A production-shaped command --
`kubectl apply`, `terraform apply`, `docker push`, a `git push` to `main` -- is expensive to
undo and easy to run by habit under time pressure, from either role. This pack asks before
either role runs one, independent of whatever pipeline step reached it, closing the same gap
`ops-approval` closes but for the role that most often actually holds the shell.

## Apply it

```bash
docket init --recipe prod-approval          # a new pod for the current directory
docket pod apply prod-approval    # onto an existing pod
```

`apply` validates the policy file and plans it (a `policy` item only), and is safe to run again
(a second run plans it `skip`). `--dry-run` prints the plan without writing.

## See it fire

```bash
docket pod apply prod-approval
docket pod check "terraform apply" --role implementer
docket pod check "git push origin main" --role operator
```

Both name `prod-approval-high-risk` and ask.

## Files

- `pod.yaml` -- `kind: pod`, `name: prod-approval`, `description`; no `members`.
- `policies/prod-approval-high-risk.yaml` -- `tool: bash` + `matches`; `appliesTo:
  [implementer, operator]`; asks on `kubectl apply|delete|replace|rollout`, `helm upgrade|
  install`, `terraform apply|destroy`, `docker push`, `npm publish`, `fly deploy`,
  `vercel --prod`, `heroku promote`, or a `git push` to a production-shaped branch.

## Undo

```bash
rm ~/.docket/workspaces/pods/<project>/config/policies/prod-approval-high-risk.yaml
```
