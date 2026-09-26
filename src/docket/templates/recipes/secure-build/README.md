# secure-build

Add a read-only Security Vetter to a codebase pod: the Implementer's change must get an
explicit `APPROVE` from the vetter before the task counts as done, with one bounded rework
cycle back to the Implementer on `REQUEST-CHANGES`.

## Apply it

Against an existing pod `<project>` (with `lead` and `implementer` already provisioned —
`docket init <project>` or `docket add <project>` gives you that):

```bash
docket roles validate roles/security-vetter.yaml
docket roles add roles/security-vetter.yaml
docket pod <project> add security-vetter

docket pipeline validate pipeline.yaml
docket pipeline plan <project> --file pipeline.yaml   # confirm nothing is skipped
docket pod <project> config set pipeline pipeline.yaml
```

Optional: copy the policy pack so a secret-shaped write always asks a human, independent of
the vetter's own verdict (paths relative to `~/.docket` unless `POLICIES_DIR` is set):

```bash
docket policies validate policies/require-approval-secret-writes.json
cp policies/require-approval-secret-writes.json ~/.docket/policies/
```

## Files

- `roles/security-vetter.yaml` — the custom role: `read-only` edit rights, `deniedTools:
  [write, edit, bash]`, `verdict` gate contract on `APPROVE`/`REQUEST-CHANGES`.
- `pipeline.yaml` — `lead -> implementer (mechanical gate, its own verifyCmd) ->
  security-vetter (verdict gate, rework -> implementer, maxCycles 1)`.
- `policies/require-approval-secret-writes.json` — optional; narrows the Implementer's exec
  surface for secret-shaped writes regardless of the vetter's own review.

## Undo

```bash
docket pod <project> config unset pipeline
docket pod <project> remove <project>-security-vetter
rm ~/.docket/policies/require-approval-secret-writes.json   # if copied
```
