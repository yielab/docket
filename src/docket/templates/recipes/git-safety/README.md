# git-safety

A policy pack: two guardrail policies, no roles, no pipeline, no members. Applying it to a pod
adds nothing to the roster and changes no dispatch step -- it only narrows what `bash` may do
inside that pod's own turns.

**Threat model, in three sentences.** An agent under time pressure (or one following an
adversarial instruction smuggled into its context) can lose real work with a single unattended
git command -- a force-push overwrites another operator's commits, `git reset --hard`/`git clean
-f` discard uncommitted work with no undo, and `git branch -D`/`git checkout -- .` destroy a
branch or working-tree edits outright. None of docket's exec allowlist or role denials stop
these: `git` itself is allowlisted (security-gates.spec.md), so the classifier never sees the
difference between `git status` and `git push --force`. This pack closes exactly that gap with
structured predicates over the call itself (`tool: bash`, `matches`, `branch`) rather than free
text, so it fires on the command regardless of which role or pipeline step issued it.

## Apply it

```bash
docket init --recipe git-safety          # a new pod for the current directory
docket pod apply git-safety    # onto an existing pod
```

`apply` validates both policy files and plans them (`policy` items only -- there is no
`pod.yaml` member to add), and is safe to run again (a second run plans every item `skip`).
`--dry-run` prints the plan without writing.

## See it fire

```bash
docket pod apply git-safety
docket pod check "git push --force origin main" --role implementer
```

The result names `git-safety-block-destructive` and blocks. A plain `git push origin main`
(destination or current branch is protected) asks instead:

```bash
docket pod check "git push origin main" --role implementer
```

## Files

- `pod.yaml` -- `kind: pod`, `name: git-safety`, `description`; no `members`, since a policy
  pack changes no roster.
- `policies/git-safety-block-destructive.yaml` -- `tool: bash` + `matches`; blocks force-push,
  `reset --hard`, forced `clean`, forced branch delete, forced checkout, and a global config
  edit, for every role.
- `policies/git-safety-ask-protected-branch-push.yaml` -- `tool: bash` + `matches: git push` AND
  (a destination-name match OR the structured `branch` predicate against `main`/`master`/
  `production`/`prod`); asks for every role.

## Undo

```bash
rm ~/.docket/workspaces/pods/<project>/config/policies/git-safety-block-destructive.yaml
rm ~/.docket/workspaces/pods/<project>/config/policies/git-safety-ask-protected-branch-push.yaml
```
