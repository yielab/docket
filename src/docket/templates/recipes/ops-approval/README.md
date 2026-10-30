# ops-approval

A policy that asks a person before the Operator runs a deploy- or production-shaped command
(`kubectl apply`, `terraform apply`, `git push` to `main`, `npm publish`, `docker push` and
the like), whatever pipeline step the command belongs to. It ships no pipeline and no members,
because the `operate` pod blueprint (`docket init --blueprint operate`) already has the Operator,
a human approval step before it acts, and a Reviewer after it. `operator` is a built-in starter
archetype (`docket pod roles`).

Use this recipe on a pod that has an `operator` member: an `operate` pod, or any pod that added
one with `docket pod add operator`.

## Apply it

```bash
docket pod update ops-approval    # onto an existing pod
```

`apply` validates the policy pack before writing anything and is safe to run again (a second run
plans every item `skip`). `--dry-run` prints the plan without writing.

Answer the resulting approval with `docket task answer <id> --option approve_once` / `--option deny` (`docket inbox` prints the exact line; also
reachable over HTTP, MCP or Telegram `/answer` — every channel is audited). Unanswered
requests are denied after `APPROVAL_TIMEOUT` (900s).

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: ops-approval`, no members.
- `policies/ops-approval-high-risk.yaml` — applied into the pod's own policy directory; it has a
  structured `tool: bash` predicate alongside its `matches`, so it only evaluates the regex
  against an actual shell command rather than every `pre_tool_call` hook's rendered text; it
  requires approval for deploy/production shaped commands from the operator role.

## Undo

```bash
rm ~/.docket/config/pods/<project>/policies/ops-approval-high-risk.yaml
```
