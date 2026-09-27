# secure-build

Add a read-only Security Vetter to a codebase pod: the Implementer's change must get an
explicit `APPROVE` from the vetter before the task counts as done, with one bounded rework
cycle back to the Implementer on `REQUEST-CHANGES`.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe secure-build          # a new pod for the current repository
docket pod <project> apply secure-build    # onto an existing pod
```

`pod.yaml` names the one member this recipe adds (`security-vetter`); `apply` validates the
role, the policy pack, the resulting roster, and `pipeline.yaml` before writing anything, and is
safe to run again (a second run plans every item `skip`). `--dry-run` prints the plan without
writing. The bundled `policies/require-approval-secret-writes.yaml` is applied along with
everything else, so a secret-shaped write always asks a human, independent of the vetter's own
verdict.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: secure-build`, `members:
  [security-vetter]`.
- `roles/security-vetter.yaml` (+ `roles/security-vetter.md`) — the custom role, short form:
  `cannot: [write, edit, bash]`, `verdict: [APPROVE, REQUEST-CHANGES]`.
- `pipeline.yaml` — `lead -> implementer (mechanical gate, its own verifyCmd) ->
  security-vetter (verdict gate, rework -> implementer, maxCycles 1)`.
- `policies/require-approval-secret-writes.yaml` — applied into the pod's own policy directory;
  rewritten on the structured predicates `core/policy.py` already evaluates (Phase 31, D-47) --
  an `anyOf` of `{tool: write, path: '**/.env*'}`, `{tool: edit, path: '**/.env*'}`, and a
  private-key-header `matches` -- so it fires on the call itself rather than the loose
  "write...env" text match it used to be, and so the Implementer's exec surface for
  secret-shaped writes still narrows regardless of the vetter's own review.

## Undo

```bash
docket pod <project> config unset pipeline
docket pod <project> remove <project>-security-vetter
rm ~/.docket/workspaces/pods/<project>/config/policies/require-approval-secret-writes.yaml
```
