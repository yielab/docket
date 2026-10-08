# secrets-guard

A policy pack: three guardrail policies, no roles, no pipeline, no members.

**Threat model, in three sentences.** An agent debugging a failing build, or one following an
instruction smuggled into its context, can read a real credential and either write it somewhere
it should never live (committing a `.env` or an SSH private key) or echo it into a hop's own
output, which the trace/audit log then holds in plain text. Path-shaped predicates catch the
first case regardless of the file's contents (an empty `.env` is just as sensitive a target as a
populated one), and text-shaped predicates catch the second regardless of which file or tool
carried the secret, because a credential can leak through a `bash` command's own arguments just
as easily as through `write`/`edit`. This pack narrows both, and redacts the same shapes from
output as a second, independent line of defense.

## Apply it

```bash
docket init --recipe secrets-guard          # a new pod for the current directory
docket pod apply secrets-guard    # onto an existing pod
```

`apply` validates all three policy files and plans them (`policy` items only), and is safe to
run again (a second run plans every item `skip`). `--dry-run` prints the plan without writing.

## See it fire

```bash
docket pod apply secrets-guard
docket pod check "" --role implementer --tool write --arg path=config/.env
docket pod check "" --role implementer --tool write --arg path=README.md
```

The first names `secrets-guard-block-paths` and blocks; the second (an ordinary path) allows.

## Files

- `pod.yaml` -- `kind: pod`, `name: secrets-guard`, `description`; no `members`.
- `policies/secrets-guard-block-paths.yaml` -- an `anyOf` of `{tool: write|edit, path: ...}`
  pairs over `**/.env*`, `**/*.pem`, `**/*.key`, `**/id_rsa*`, `**/*.p12`; blocks.
- `policies/secrets-guard-block-credential-text.yaml` -- a `matches` over the rendered call for
  a private-key header, an AWS access-key id shape, or an `sk`-prefixed bearer-token shape, no
  tool restriction; blocks.
- `policies/secrets-guard-redact-output.yaml` -- the same three text shapes, `on: output`;
  redacts rather than blocks, since output has already been produced and the goal is keeping it
  out of the trace/audit record, not stopping the hop.

## Undo

```bash
rm ~/.docket/workspaces/pods/<project>/config/policies/secrets-guard-block-paths.yaml
rm ~/.docket/workspaces/pods/<project>/config/policies/secrets-guard-block-credential-text.yaml
rm ~/.docket/workspaces/pods/<project>/config/policies/secrets-guard-redact-output.yaml
```
