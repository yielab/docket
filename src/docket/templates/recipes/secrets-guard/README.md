# secrets-guard

A policy pack: two guardrail policies, no roles, no pipeline, no members.

**Threat model, in three sentences.** An agent debugging a failing build, or one following an
instruction smuggled into its context, can read a real credential and either write it somewhere
it should never live (committing a `.env` or an SSH private key) or carry it in a tool call's own
text. Path-shaped predicates catch the first case regardless of the file's contents (an empty `.env`
is just as sensitive a target as a populated one), and text-shaped predicates catch the second
regardless of which file or tool carried the secret, because a credential can leak through a `bash`
command's own arguments just as easily as through `write`/`edit`. This pack narrows both.
Redacting a credential out of a hop's output is built in and always on
(`docket.governance.secrets.redact`), so the pack carries no output rule.

## Apply it

```bash
docket init --recipe secrets-guard          # a new pod for the current directory
docket pod update secrets-guard    # onto an existing pod
```

`apply` validates both policy files and plans them (`policy` items only), and is safe to
run again (a second run plans every item `skip`). `--dry-run` prints the plan without writing.

## See it fire

```bash
docket pod update secrets-guard
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

## Undo

```bash
rm ~/.docket/config/pods/<project>/policies/secrets-guard-block-paths.yaml
rm ~/.docket/config/pods/<project>/policies/secrets-guard-block-credential-text.yaml
```
